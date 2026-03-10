# LEARNINGS.md — Engineering Decisions & Implementation Notes

> Captures key technical challenges, failed approaches, and final solutions
> encountered while building the Human Emulation Desktop Agent.

---

## 1. OmniParser Integration

> How Emu uses OmniParser V2 to give the VLM precise UI element coordinates
> on every screenshot, eliminating coordinate guessing.

### The Problem

Vision-language models are good at understanding what's on screen but bad at
pinpointing exact pixel coordinates for click targets. When Emu's VLM says
"click the File menu," it has to estimate where (x=25, y=12) is — and it's
often off by 10–30 pixels. This leads to missed clicks, wrong targets, and
wasted retry loops.

### The Solution

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

### Architecture

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

### OmniParser V2 — Deep Dive

OmniParser is an open-source screen parsing framework from Microsoft Research.
Its job: take any screenshot and return a structured list of every interactable
UI element on screen with bounding boxes.

#### The core insight: UI elements are two fundamentally different things

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

#### Component 1: YOLO (icon / button detection)

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

#### Component 2: EasyOCR (text detection + recognition)

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

#### Why both models together?

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

#### Component 3: remove_overlap_new() (merge + deduplication)

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

#### Component 4: Custom PIL annotation (our addition)

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

#### The full pipeline, step by step

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

#### Why not use a single multimodal model instead?

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

#### Build-time patches (why we can't just use OmniParser stock)

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

### OmniParser on Modal

OmniParser V2 runs on an **A10G GPU** via Modal serverless infrastructure.

**Why Modal?**
- YOLO + EasyOCR need GPU — running locally would be slow and require CUDA
- Modal cold-starts in ~15s, warm requests take ~1.5s
- `min_containers=1` keeps one container warm at all times

**Pipeline (inside the GPU container):**

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

**Deployment:**
```bash
cd backend/providers/modal/omni_parser
modal deploy deploy.py
```

### Performance

| Metric | Value |
|---|---|
| OmniParser latency (warm) | ~1.5–1.7s |
| OmniParser latency (cold) | ~15–20s (first request) |
| Elements detected (typical desktop) | 80–150 |
| GPU | NVIDIA A10G (Modal) |
| Concurrent requests | Up to 8 per container |
| Min containers | 1 (always warm) |

### Data Flow Summary

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

---

## 2. Cursor-Visible Screenshot Capture

> How we replaced Electron's `desktopCapturer` with a PowerShell-based screen
> capture pipeline that includes the mouse cursor and handles DPI scaling.

### The Problem

Electron's `desktopCapturer.getSources()` calls into Windows' Desktop
Duplication API (DXGI) or Windows Graphics Capture. These APIs capture the
**composed desktop framebuffer** — what's rendered to the display minus the
hardware cursor. Windows renders the cursor in a separate hardware overlay
that these capture APIs intentionally skip.

**Result:** The model receives screenshots with no cursor visible, making it
impossible for the VLM to know where the pointer currently is on screen.
This hurts spatial grounding — the model can't verify "did my mouse_move
actually land on the right target?"

### Failed Approaches

#### Attempt 1: `Cursors.Default.Draw()` with `Screen.PrimaryScreen.Bounds`

```powershell
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$cur = [System.Windows.Forms.Cursors]::Default
$cur.Draw($g, (New-Object System.Drawing.Rectangle($pos.X, $pos.Y, ...)))
```

**Problem: DPI scaling.** On displays with 125%/150%/200% scaling,
`Screen.PrimaryScreen.Bounds` returns **logical pixels** (e.g., 1664×1109),
not physical pixels (e.g., 2496×1664). `CopyFromScreen` uses the logical
dimensions to grab from the physical framebuffer, so it only captures the
top-left portion of the screen — the rest is cropped.

Additionally, `Cursors.Default.Draw()` rendered a tiny, nearly invisible
system cursor icon that didn't scale with DPI and always showed the default
arrow regardless of the actual cursor shape.

#### Attempt 2: `SetProcessDPIAware()` (user32.dll)

```powershell
[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
```

**Problem:** This sets "System DPI aware" — the legacy mode. On modern
Windows with per-monitor scaling, it still doesn't report the true physical
resolution. `Screen.Bounds` continued returning logical coordinates.

#### Attempt 3: `SetProcessDpiAwareness(2)` (shcore.dll)

```powershell
[DllImport("shcore.dll")] public static extern int SetProcessDpiAwareness(int value);
```

Passing `2` = `PROCESS_PER_MONITOR_DPI_AWARE` — the modern approach.

**Problem:** Returned `E_ACCESSDENIED` (-2147024891). DPI awareness can only
be set before any UI-related DLLs load, and PowerShell had already loaded
`System.Windows.Forms` by this point. Too late to change it.

### The Working Solution

#### Step 1: Get true physical resolution via `GetDeviceCaps`

Instead of relying on DPI awareness settings, query the **device capabilities**
directly from the GDI device context:

```powershell
[DllImport("gdi32.dll")] public static extern int GetDeviceCaps(IntPtr hdc, int index);
[DllImport("user32.dll")] public static extern IntPtr GetDC(IntPtr hwnd);
[DllImport("user32.dll")] public static extern int ReleaseDC(IntPtr hwnd, IntPtr hdc);

$hdc = [W.GDI]::GetDC([IntPtr]::Zero)           # desktop DC
$physicalWidth  = [W.GDI]::GetDeviceCaps($hdc, 118)  # DESKTOPHORZRES
$physicalHeight = [W.GDI]::GetDeviceCaps($hdc, 117)  # DESKTOPVERTRES
[W.GDI]::ReleaseDC([IntPtr]::Zero, $hdc)
```

- `GetDeviceCaps(hdc, 118)` = `DESKTOPHORZRES` → **true physical width**
- `GetDeviceCaps(hdc, 117)` = `DESKTOPVERTRES` → **true physical height**
- These always return the real resolution regardless of DPI settings or
  process awareness level.

#### Step 2: Capture at physical resolution

```powershell
$bmp = New-Object System.Drawing.Bitmap($physicalWidth, $physicalHeight)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen(0, 0, 0, 0, (New-Object System.Drawing.Size($w, $h)))
```

Using the physical dimensions means `CopyFromScreen` grabs the entire
framebuffer — no cropping.

#### Step 3: Convert cursor position from logical to physical

`Cursor.Position` returns logical coordinates (since our process isn't
DPI-aware). We compute the DPI scale ratio and convert:

```powershell
$pos = [System.Windows.Forms.Cursor]::Position
$dpiScale = $physicalWidth / [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width
$px = [int]($pos.X * $dpiScale)
$py = [int]($pos.Y * $dpiScale)
```

For a 150% scaled display: `dpiScale = 2496 / 1664 = 1.5`

#### Step 4: Draw a cursor-shaped polygon

Instead of using `Cursors.Default.Draw()` (which has its own DPI issues and
always shows the default arrow in tiny size), we draw a **custom arrow polygon**
using GDI+ primitives — a filled white shape with a black border:

```powershell
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$s = 1.8 * $dpiScale    # scale factor — cursor grows with DPI

# 7-point polygon shaped like a Windows cursor arrow
$pts = @(
  PointF($px, $py),                                    # tip (top-left)
  PointF($px,                ($py + [int](20*$s))),     # down left edge
  PointF(($px + [int](4*$s)),  ($py + [int](16*$s))),  # notch left
  PointF(($px + [int](8*$s)),  ($py + [int](22*$s))),  # tail bottom-left
  PointF(($px + [int](11*$s)), ($py + [int](19*$s))),  # tail bottom-right
  PointF(($px + [int](7*$s)),  ($py + [int](13*$s))),  # notch right
  PointF(($px + [int](13*$s)), ($py + [int](13*$s)))   # right wing
)

$g.FillPolygon([Brushes]::White, $pts)                  # white fill
$pen = New-Object Pen([Color]::Black, [Math]::Max(2, [int](1.5*$dpiScale)))
$g.DrawPolygon($pen, $pts)                              # black border
```

**Why a custom polygon instead of the system cursor icon:**
- The system `Cursor.Draw()` doesn't scale with DPI — it's tiny on HiDPI screens
- It always draws the default arrow, never the actual cursor shape (I-beam, hand, etc.)
- A custom polygon scales perfectly with `$dpiScale` and is always visible
- Anti-aliased edges make it look clean at any resolution
- The white fill with black border ensures visibility against any background

### Integration: Persistent PowerShell Process

All capture commands run through `psProcess` — a single long-lived PowerShell
process started when the Electron app launches. This avoids the 300–700ms
cold-start of spawning a new `powershell.exe` per screenshot.

At startup, `psProcess` preloads the required types:

```javascript
// psProcess.js — preloaded at start()
'Add-Type -AssemblyName System.Windows.Forms'          // Forms, Cursor, Screen

// P/Invoke types for mouse/keyboard actions
'[DllImport("user32.dll")] ... mouse_event ...'
'[DllImport("user32.dll")] ... keybd_event ...'

// GDI types for physical-pixel screen capture
'[DllImport("gdi32.dll")] ... GetDeviceCaps ...'
'[DllImport("user32.dll")] ... GetDC ...'
'[DllImport("user32.dll")] ... ReleaseDC ...'
```

These are loaded once and persist for the lifetime of the process.

Each screenshot command is sent via `psProcess.run()`, which Base64-encodes
the command, pipes it to stdin, and waits for a sentinel marker (##PS_DONE##)
on stdout. The command saves the PNG to disk and writes the base64 string to
stdout in one pass — no separate file read needed.

### Files Changed

| File | Change |
|---|---|
| `frontend/process/psProcess.js` | Added GDI P/Invoke type preloading (`GetDeviceCaps`, `GetDC`, `ReleaseDC`) |
| `frontend/actions/screenshot.js` | Replaced `desktopCapturer` with PowerShell capture (GetDeviceCaps + cursor polygon) |
| `frontend/actions/fullCapture.js` | Same — also moves window off-screen before capture, restores after |
| `main.js` | Removed `desktopCapturer` import (no longer needed) |

### Performance

| Aspect | Old (`desktopCapturer`) | New (PowerShell) |
|---|---|---|
| Capture API | DXGI / WGC (GPU-accelerated) | GDI+ BitBlt (CPU) |
| Cursor | Not included | Custom polygon at true position |
| DPI handling | Electron handles it | GetDeviceCaps for physical resolution |
| Latency | ~50–100ms | ~100–200ms |
| Process spawn | None (in-process) | None (reuses persistent PowerShell) |

The ~50–100ms extra latency is negligible in the agent loop (which already
includes 1.5s for OmniParser + 2–5s for VLM reasoning).

### Key Takeaway

Windows screen capture APIs (DXGI, WGC, GDI+) all exclude the hardware
cursor by design. There's no flag to include it. The only option is to
composite the cursor after capture. And when doing GDI+ capture on HiDPI
displays, you **cannot rely on `Screen.Bounds`** — it returns logical pixels
unless the process is DPI-aware before any UI DLLs load (which PowerShell
isn't). `GetDeviceCaps(DESKTOPHORZRES/DESKTOPVERTRES)` is the reliable path
to true physical pixel resolution.
