# OmniParser Integration

> How Emu uses OmniParser V2 to give the VLM precise UI element coordinates
> on every screenshot, eliminating coordinate guessing.

---

## The Problem

Vision-language models are good at understanding what's on screen but bad at
pinpointing exact pixel coordinates for click targets. When Emu's VLM says
"click the File menu," it has to estimate where (x=25, y=12) is — and it's
often off by 10–30 pixels. This leads to missed clicks, wrong targets, and
wasted retry loops.

## The Solution

Every screenshot now passes through **OmniParser V2** before reaching the
model. OmniParser is a computer vision pipeline (YOLO + EasyOCR) that
detects all visible UI elements — buttons, icons, text labels, inputs,
menus — and returns their exact bounding boxes in pixel coordinates.

The model receives:
1. **An annotated image** — the screenshot with thin colored boxes drawn
   around each element (red for icons, cyan for text) with ID labels
2. **A structured element list** — every element's ID, type, content,
   bounding box, center point, and clickability flag

The model's job stays the same — understand context, reason about what
to do next — but now it has precise click targets instead of guessing.

---

## Architecture

```
Frontend screenshot (base64 PNG)
        │
        ▼
┌─────────────────────────────────────────────────┐
│          context_manager.add_screenshot_turn()   │
│                                                  │
│  1. Send base64 to OmniParser client             │
│  2. OmniParser client → Modal GPU endpoint       │
│  3. Modal runs YOLO + EasyOCR in parallel        │
│  4. Returns: annotated image + element list      │
│  5. Store annotated image as the screenshot       │
│  6. Attach ScreenAnnotation to PreviousMessage   │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│          context_manager.build_request()          │
│                                                  │
│  Latest screenshot → kept as annotated image     │
│  Element list → injected as [SCREEN ELEMENTS]    │
│  text message right after the screenshot         │
│  Older screenshots → replaced with placeholder   │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
              VLM sees image + elements
              → reasons → picks action
              → uses precise coordinates
```

---

## OmniParser V2 — Deep Dive

OmniParser is an open-source screen parsing framework from Microsoft Research.
Its job: take any screenshot and return a structured list of every interactable
UI element on screen with bounding boxes. Understanding **why** it's built the
way it is requires understanding why no single model can do this job alone.

### The core insight: UI elements are two fundamentally different things

A desktop screenshot contains two kinds of targets a user might click:

1. **Icons / buttons / visual controls** — the Start button, close/minimize
   icons, toolbar buttons, checkboxes, sliders, toggle switches, avatar images.
   These are *visual patterns* — they look like something clickable but contain
   no readable text.

2. **Text labels / links / menu items** — "File", "Edit", "Save As...", a URL
   in the address bar, a button that says "Submit". These are *readable strings*
   at known positions.

No single model handles both well:
- An **object detector** (YOLO) is great at recognising visual patterns
  ("that's a button shape", "that's an icon") but can't read the text inside.
- An **OCR engine** (EasyOCR) is great at reading text but doesn't know whether
  "File" is a menu item, a filename, or decorative label — and it misses
  anything that's purely visual (a gear icon, a hamburger menu ☰).

OmniParser's architecture **runs both in parallel and merges the results**.

### Component 1: YOLO (icon / button detection)

**What**: YOLOv8, fine-tuned by Microsoft on a large dataset of desktop and web
UI screenshots. The training data contains labelled bounding boxes for icons,
buttons, toggles, sliders, checkboxes, and other visual controls.

**Why YOLO specifically**: YOLO (You Only Look Once) is a single-pass object
detector — it processes the entire image in one forward pass through the neural
network and outputs all detected objects simultaneously. This makes it very fast
(~200ms on an A10G for a 1920×1080 screenshot). Unlike two-stage detectors
(Faster R-CNN), there's no separate "region proposal" step.

**What it returns**: For each detected icon/button:
- Bounding box coordinates `[x1, y1, x2, y2]` in pixels
- Confidence score (we threshold at 0.05 — very permissive, to catch small icons)
- Class label (not very useful — OmniParser maps everything to "icon")

**What it misses**: Text-based UI elements. YOLO sees "File Edit View" in the
menu bar as a flat region, not three separate clickable items.

**Weights location** (inside the Modal container):
```
/opt/omniparser/weights/icon_detect/model.pt    # Fine-tuned YOLOv8
/opt/omniparser/weights/icon_detect/model.yaml  # Architecture config
```

### Component 2: EasyOCR (text detection + recognition)

**What**: EasyOCR is a PyTorch-based OCR engine. It runs two models internally:
1. **CRAFT** (Character Region Awareness for Text detection) — finds regions in
   the image that contain text, outputs bounding boxes
2. **Recognition network** — reads the actual characters inside each box

**Why EasyOCR over PaddleOCR**: OmniParser originally shipped with PaddleOCR
(based on PaddlePaddle framework). We switched because:
- PaddlePaddle GPU requires cuDNN libraries that aren't in Modal's debian_slim
- Installing cuDNN adds ~2GB to the container image and is fragile
- PaddlePaddle and PyTorch use different CUDA runtimes — loading both wastes GPU
  memory and causes conflicts
- EasyOCR is PyTorch-native — it shares the exact same CUDA/cuDNN stack as YOLO,
  zero additional dependencies, ~400MB smaller container

**What it returns**: For each text region:
- Bounding box `[x1, y1, x2, y2]`
- Recognised text string (e.g., "File", "Save As...", "https://github.com")
- Confidence score

**What it misses**: Purely visual elements. A gear icon ⚙, a close button ✕,
or a colored toggle switch contain no text — EasyOCR can't detect them.

**Configuration** in our pipeline:
```python
easyocr_args = {"paragraph": False, "text_threshold": 0.9}
```
- `paragraph=False` — don't merge nearby text into paragraphs. We want each
  "File", "Edit", "View" as separate elements, not "File Edit View".
- `text_threshold=0.9` — only accept high-confidence text to reduce noise.

### Why both models together?

Consider a typical application window:

```
┌─────────────────────────────────────────────────┐
│ [icon] File  Edit  View  Help           [─][□][✕]│  ← menu bar
│─────────────────────────────────────────────────│
│ [icon][icon][icon]  |  Search...                │  ← toolbar
│─────────────────────────────────────────────────│
│                                                  │
│  Content area                                    │
│                                                  │
│  [Save]  [Cancel]                                │  ← buttons with text
│                                                  │
└─────────────────────────────────────────────────┘
```

- **YOLO detects**: `[icon]` buttons, `[─]` `[□]` `[✕]` controls, toolbar icons,
  `[Save]` and `[Cancel]` as button shapes
- **EasyOCR detects**: "File", "Edit", "View", "Help", "Search...", "Save",
  "Cancel" as text strings at specific positions
- **Overlap**: Both detect the `[Save]` button — YOLO sees the button shape,
  EasyOCR reads "Save" inside it

Without merging, the VLM would see duplicate entries for every text button.
That's where the merge step comes in.

### Component 3: remove_overlap_new() (merge + deduplication)

After both models finish, we have two lists of bounding boxes that partially
overlap. OmniParser's `remove_overlap_new()` function resolves this:

```
YOLO boxes (icons)     +     EasyOCR boxes (text)
        │                            │
        └────────────┬───────────────┘
                     ▼
            remove_overlap_new()
                     │
            ┌────────┴──────────┐
            │  For each pair:   │
            │  compute IoU      │
            │  (Intersection    │
            │   over Union)     │
            │                   │
            │  If IoU > thresh: │
            │  keep the text    │
            │  box (has content)│
            │  discard icon box │
            └────────┬──────────┘
                     │
                     ▼
            Deduplicated element list
            (no double-counted buttons)
```

**IoU (Intersection over Union)**: Measures how much two boxes overlap.
IoU = area_of_overlap / area_of_union. Our threshold is 0.1 — even 10%
overlap triggers dedup.

**Why keep text over icon**: When a button has both a YOLO detection and an
EasyOCR detection, we keep the text version because it carries the readable
label ("Save") which the VLM can use for reasoning. An icon-only detection
just says "there's a clickable thing at (200, 400)".

### Component 4: Custom PIL annotation (our addition)

OmniParser ships with an `annotate()` function that draws numbered boxes on
the screenshot. We replaced it because:

- **Thick lines**: The original uses 3–4px wide rectangles in rainbow colors.
  On a 1920×1080 desktop with 130+ elements, the boxes overlap and cover the
  actual UI, making the screenshot unreadable for the VLM.
- **Large labels**: Numbered labels in big fonts stack up and overlap.
- **Slow**: It uses matplotlib rendering which adds ~500ms.

Our replacement uses PIL (Pillow) directly:
- **1px thin** rectangles — visible but don't obscure content
- **Red** for icons, **cyan** for text — two-color palette, easy to distinguish
- **Small ID labels** (11px DejaVu Sans) positioned just above each box
- **~50ms** instead of ~500ms

### The full pipeline, step by step

```
1. Screenshot arrives as base64 PNG
       │
2. Decode → PIL Image → save to temp file
   (OmniParser's functions expect file paths, not PIL objects)
       │
3. ThreadPoolExecutor launches two threads:
       │
       ├─── Thread A: check_ocr_box()
       │    └── EasyOCR Reader.readtext()
       │        └── CRAFT text detector → box coordinates
       │        └── Recognition net → text strings
       │    └── Returns: (text_list, bbox_list) in pixel coords
       │
       ├─── Thread B: predict_yolo()
       │    └── YOLOv8 forward pass on resized image (640px)
       │    └── NMS (non-max suppression) removes duplicate boxes
       │    └── Returns: (xyxy_tensor, logits, phrases)
       │
4. Both threads complete (~1.3s total, parallel)
       │
5. Normalize all coordinates to 0–1 range
   (divide by image width/height)
       │
6. Build element dicts with type, bbox, content, source
       │
7. remove_overlap_new(icon_elems, ocr_elems, iou_threshold=0.1)
   → deduplicated list
       │
8. Convert back to pixel coordinates
   → build response with id, type, content, bbox_pixel, center_pixel
       │
9. (Optional) Draw annotation using PIL
   → 1px boxes, red/cyan, small ID labels
   → encode to base64
       │
10. Return JSON response
```

### Why not use a single multimodal model instead?

You might wonder: GPT-4o and Claude can "see" screenshots — why not just ask
them to identify elements? Several reasons:

1. **Speed**: A VLM call takes 2–5s and costs tokens. OmniParser takes 1.5s
   and costs only GPU compute (much cheaper).
2. **Precision**: VLMs estimate coordinates with ~10–30px error. YOLO/OCR are
   pixel-precise — they detect exact bounding boxes.
3. **Reliability**: VLMs hallucinate elements that don't exist or miss small
   icons. YOLO/OCR are deterministic — same image → same detections.
4. **Separation of concerns**: Detection (where are things?) is a different
   task from reasoning (what should I do?). Using a specialist for each is
   more robust than asking one model to do both.

The VLM's job becomes easier: instead of "figure out where the File menu is
and guess coordinates," it's "look up element [1] TEXT 'File' → click center
(25, 12)." The VLM focuses on understanding and planning; OmniParser handles
perception.

### Build-time patches (why we can't just use OmniParser stock)

OmniParser V2's codebase has a few assumptions that break in our environment:

**1. Module-level PaddleOCR init**
```python
# util/utils.py line 23 (original)
paddle_ocr = PaddleOCR(use_angle_cls=True, lang="en", use_gpu=True)
```
This runs at *import time* — before any of our code executes. Since we don't
install PaddlePaddle, this crashes immediately. We patch it at build time:
```python
# After our regex patch
paddle_ocr = None
```

**2. EasyOCR reader injection**
OmniParser's `check_ocr_box()` uses a module-level `reader` variable. We
create our own EasyOCR Reader with `gpu=True` and patch it in:
```python
import util.utils as _utils
_utils.reader = easyocr.Reader(["en"], gpu=True)
```

**3. scale_img parameter**
A recent OmniParser update added a required `scale_img` parameter to
`predict_yolo()`. All internal callers use `False`. We pass it explicitly.

---

## OmniParser on Modal

OmniParser V2 runs on an **A10G GPU** via Modal serverless infrastructure.

### Why Modal?
- YOLO + EasyOCR need GPU — running locally would be slow and require CUDA
- Modal cold-starts in ~15s, warm requests take ~1.5s
- `min_containers=1` keeps one container warm at all times

### Pipeline (inside the GPU container)

```
Input: base64 PNG screenshot
        │
        ├─── Thread 1: EasyOCR ──→ text regions + OCR content
        │
        ├─── Thread 2: YOLO ─────→ icon/button bounding boxes
        │
        └─── Merge ──────────────→ remove_overlap_new()
                                         │
                                         ▼
                                  Deduplicated element list
                                  + annotated image (optional)
```

**Key decisions:**
- **EasyOCR over PaddleOCR**: PaddlePaddle GPU crashed with cuDNN errors on
  Modal's debian_slim. EasyOCR is PyTorch-based — shares the same CUDA stack
  as YOLO with zero compatibility issues.
- **Build-time patch**: OmniParser's `util/utils.py` creates a `PaddleOCR()`
  instance at module level (line 23) which crashes on import. We patch it to
  `None` via regex at Docker build time.
- **Parallel execution**: OCR and YOLO are independent — running them in a
  `ThreadPoolExecutor` cuts latency vs sequential.
- **Custom annotation**: OmniParser's built-in `annotate()` draws thick
  rainbow boxes that obscure the screen. We draw our own with PIL: 1px thin
  rectangles, red for icons, cyan for text, small ID labels.

### File structure

```
backend/providers/modal/omni_parser/
├── __init__.py     # Re-exports client functions
├── deploy.py       # Modal deployment definition (modal deploy deploy.py)
└── client.py       # Python client: parse_screenshot(), parse_screenshot_b64()
```

### Deployment

```bash
cd backend/providers/modal/omni_parser
modal deploy deploy.py
```

Endpoints after deploy:
- **Parse**: `POST https://ppbhatt500--omniparser-v2-omniparserv2-parse.modal.run`
- **Health**: `GET  https://ppbhatt500--omniparser-v2-omniparserv2-health.modal.run`

---

## Pydantic Models

Two new models in `models/request.py`:

### ScreenElement
```python
class ScreenElement(BaseModel):
    id:           int           # Matches the label drawn on the annotated image
    type:         str           # "icon" | "text"
    content:      str           # OCR text (empty for icons)
    bbox_pixel:   list[int]     # [x1, y1, x2, y2] in pixels
    center_pixel: list[int]     # [cx, cy] — the click target
    interactable: bool
```

### ScreenAnnotation
```python
class ScreenAnnotation(BaseModel):
    elements:     list[ScreenElement]
    image_width:  int
    image_height: int
    latency_ms:   int
```

`PreviousMessage` now has an optional `annotations: ScreenAnnotation` field,
populated only on screenshot messages.

---

## Context Chain Integration

### add_screenshot_turn()

Before (old):
```
screenshot base64 → store as user message → done
```

After (new):
```
screenshot base64
  → call parse_screenshot_b64(include_annotated=True)
  → replace raw screenshot with annotated image
  → build ScreenAnnotation from element list
  → store as user message with annotations attached
```

If OmniParser fails (network error, timeout), the raw screenshot is used
as a fallback — the agent still works, just without precise coordinates.

### build_request()

For the latest screenshot, after appending the image message, we now also
inject a text message containing the formatted element list:

```
[SCREEN ELEMENTS] 1920x1080 — 47 elements detected
  [0] ICON  bbox=(0,1040,48,1080)  center=(24,1060)  [clickable]
  [1] TEXT "File"  bbox=(5,0,45,25)  center=(25,12)  [clickable]
  [2] TEXT "Edit"  bbox=(50,0,90,25)  center=(70,12)  [clickable]
  ...
```

This gives the model both visual (annotated image with boxes) and structured
(text element list with coordinates) information about the screen.

---

## System Prompt Changes

Added to §2 (System Information):
- Full description of OmniParser screen analysis
- What the model receives (annotated image + element list)
- How to use element coordinates for precise clicks
- Example element list format

Updated in §3 and §10:
- Rule 5: "Prefer using center_pixel coordinates from [SCREEN ELEMENTS]"
- Rule R8: "When clicking, prefer precise coordinates from [SCREEN ELEMENTS]"

---

## Performance

| Metric | Value |
|---|---|
| OmniParser latency (warm) | ~1.5–1.7s |
| OmniParser latency (cold) | ~15–20s (first request) |
| Elements detected (typical desktop) | 80–150 |
| GPU | NVIDIA A10G (Modal) |
| Concurrent requests | Up to 8 per container |
| Min containers | 1 (always warm) |

The ~1.5s added latency per screenshot is worth it — the model gets exact
coordinates instead of guessing, which reduces failed clicks and retry loops
significantly.

---

## Data Flow Summary

```
User types task
    ↓
Frontend sends screenshot (base64)
    ↓
Backend: add_screenshot_turn()
    ├── OmniParser client → Modal GPU
    │     ├── EasyOCR (text detection)
    │     └── YOLO (icon detection)
    │     → merge → annotated image + elements
    ├── Replace raw screenshot with annotated version
    └── Attach ScreenAnnotation to message
    ↓
Backend: build_request()
    ├── Latest screenshot (annotated) as image
    ├── [SCREEN ELEMENTS] text block injected after image
    └── Older screenshots → placeholder text
    ↓
VLM receives: annotated image + element list + conversation history
    ↓
VLM reasons → picks action → uses center_pixel for mouse_move
    ↓
Frontend executes action → captures new screenshot → repeat
```
