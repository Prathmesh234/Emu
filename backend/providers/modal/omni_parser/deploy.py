"""
OmniParser V2 — Modal GPU Service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Detects UI elements (icons + text) on desktop screenshots using:
  • YOLO  — icon/button detection (OmniParser fine-tuned weights)
  • EasyOCR — text detection (PyTorch GPU, shares CUDA with YOLO)

Both run in parallel on an A10G GPU. We bypass OmniParser's slow
get_som_labeled_img() and call the primitives directly.

Deploy:  modal deploy omni_parser.py
Test:    modal serve omni_parser.py
"""

import modal

# ── Container image ──────────────────────────────────────────────────────────
# Clones OmniParser, downloads YOLO weights, installs deps, then patches out
# the module-level PaddleOCR init (crashes on newer paddleocr versions).
# We use EasyOCR instead — same PyTorch/CUDA stack as YOLO, zero cuDNN issues.

omniparser_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "libgl1-mesa-glx", "libglib2.0-0",
                 "libsm6", "libxext6", "libxrender-dev", "libgomp1")
    .run_commands("git clone https://github.com/microsoft/OmniParser.git /opt/omniparser")
    .pip_install("huggingface_hub", "hf_transfer")
    .run_commands(
        "hf download microsoft/OmniParser-v2.0 "
        "icon_detect/train_args.yaml icon_detect/model.pt icon_detect/model.yaml "
        "--local-dir /opt/omniparser/weights",
    )
    .run_commands("cd /opt/omniparser && pip install -r requirements.txt", gpu="A10G")
    .pip_install("easyocr", "fastapi[standard]", "python-multipart")
    # Patch out PaddleOCR's module-level init that crashes on import
    .run_commands(
        'python3 -c "'
        "import re, pathlib; "
        "p = pathlib.Path('/opt/omniparser/util/utils.py'); "
        "src = p.read_text(); "
        r"src = re.sub(r'(?m)^paddle_ocr\s*=\s*PaddleOCR\(.*?\)\s*$', "
        "'paddle_ocr = None', src, count=1, flags=re.DOTALL); "
        'p.write_text(src)"'
    )
    .env({"PYTHONPATH": "/opt/omniparser"})
)

app = modal.App("omniparser-v2", image=omniparser_image)


# ── GPU Service ──────────────────────────────────────────────────────────────

@app.cls(gpu="A10G", timeout=300, scaledown_window=300, min_containers=1)
@modal.concurrent(max_inputs=8)
class OmniParserV2:

    @modal.enter()
    def load_models(self):
        """Load YOLO + EasyOCR on GPU, pre-warm with a dummy image."""
        import sys, tempfile, os
        sys.path.insert(0, "/opt/omniparser")

        from util.utils import get_yolo_model, predict_yolo, check_ocr_box, remove_overlap_new
        import util.utils as _utils
        import easyocr
        from PIL import Image as _PILImage

        # YOLO icon detector
        self.yolo = get_yolo_model(model_path="/opt/omniparser/weights/icon_detect/model.pt")

        # EasyOCR on GPU — patch into OmniParser's module so check_ocr_box uses it
        self._reader = easyocr.Reader(["en"], gpu=True)
        _utils.reader = self._reader

        # Store references to OmniParser primitives
        self._predict_yolo = predict_yolo
        self._check_ocr = check_ocr_box
        self._remove_overlap = remove_overlap_new

        # Warm-up: run both models once so first real request is fast
        dummy = _PILImage.new("RGB", (640, 480), (255, 255, 255))
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        dummy.save(tmp, format="PNG"); tmp.close()
        try:
            self._check_ocr(tmp.name, display_img=False, output_bb_format="xyxy",
                            goal_filtering=None, easyocr_args={"paragraph": False, "text_threshold": 0.9},
                            use_paddleocr=False)
            self._predict_yolo(model=self.yolo, image=tmp.name,
                               box_threshold=0.05, imgsz=640, scale_img=False)
        except Exception:
            pass  # warm-up exceptions are fine
        os.unlink(tmp.name)
        print("[omniparser] Models loaded and warmed up.")

    @modal.fastapi_endpoint(method="POST")
    async def parse(self, request: dict):
        """
        Detect all UI elements in a screenshot.

        Request:  { image_base64, box_threshold?, iou_threshold?, imgsz?, include_annotated? }
        Response: { elements[], image_width, image_height, latency_ms, annotated_image_base64? }
        """
        import base64, io, os, time, tempfile
        from concurrent.futures import ThreadPoolExecutor
        import torch
        from PIL import Image

        start = time.time()

        # Parse request
        image_b64 = request.get("image_base64", "")
        box_thresh = request.get("box_threshold", 0.05)
        iou_thresh = request.get("iou_threshold", 0.1)
        imgsz = request.get("imgsz", 640)
        include_annotated = request.get("include_annotated", False)

        # Decode image, save to temp file (OmniParser needs a file path)
        image = Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")
        W, H = image.size
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            image.save(f, format="PNG"); temp_path = f.name

        # ── Run OCR + YOLO in parallel (they're independent) ─────────────
        def _ocr():
            texts, bboxes = self._check_ocr(
                temp_path, display_img=False, output_bb_format="xyxy",
                goal_filtering=None, easyocr_args={"paragraph": False, "text_threshold": 0.9},
                use_paddleocr=False)
            return texts, bboxes

        def _yolo():
            return self._predict_yolo(
                model=self.yolo, image=temp_path,
                box_threshold=box_thresh, imgsz=imgsz, scale_img=False)

        with ThreadPoolExecutor(max_workers=2) as pool:
            ocr_fut, yolo_fut = pool.submit(_ocr), pool.submit(_yolo)
            ocr_texts, ocr_bboxes = ocr_fut.result()
            xyxy, logits, phrases = yolo_fut.result()

        # ── Merge detections (remove overlapping boxes) ──────────────────
        from util.utils import int_box_area

        # Guard against None returns from check_ocr_box
        if ocr_texts is None:
            ocr_texts = []
        if ocr_bboxes is None:
            ocr_bboxes = []

        # Normalise pixel coords → 0-1 ratios
        scale = torch.Tensor([W, H, W, H])
        xyxy_norm = xyxy / scale.to(xyxy.device)
        ocr_norm = torch.tensor(ocr_bboxes) / scale if len(ocr_bboxes) else torch.empty(0, 4)

        # Build element dicts for OmniParser's merge function
        ocr_elems = [{"type": "text", "bbox": b.tolist(), "interactivity": False,
                       "content": t, "source": "box_ocr_content_ocr"}
                      for b, t in zip(ocr_norm, ocr_texts) if int_box_area(b.tolist(), W, H) > 0]
        icon_elems = [{"type": "icon", "bbox": b, "interactivity": True,
                        "content": None, "source": "box_yolo_content_yolo"}
                       for b in xyxy_norm.tolist() if int_box_area(b, W, H) > 0]

        merged = self._remove_overlap(boxes=icon_elems, iou_threshold=iou_thresh, ocr_bbox=ocr_elems)

        # Normalize: remove_overlap_new returns plain [x1,y1,x2,y2] lists
        # instead of dicts when ocr_bbox is falsy (empty/None) — OmniParser bug
        merged = [
            item if isinstance(item, dict) else
            {"type": "icon", "bbox": item, "interactivity": True,
             "content": None, "source": "box_yolo_content_yolo"}
            for item in merged
        ]

        # ── Build response ───────────────────────────────────────────────
        elements = []
        for idx, item in enumerate(merged):
            x1, y1, x2, y2 = item["bbox"]
            content = item.get("content") or ""
            if isinstance(content, list):
                content = " ".join(str(c) for c in content)
            elements.append({
                "id": idx,
                "type": item.get("type", "icon"),
                "content": str(content),
                "bbox_pixel": [int(x1*W), int(y1*H), int(x2*W), int(y2*H)],
                "center_pixel": [int((x1+x2)/2*W), int((y1+y2)/2*H)],
                "interactable": item.get("interactivity", True),
            })

        elapsed = int((time.time() - start) * 1000)
        print(f"[omniparser] {elapsed}ms — {len(elements)} elements")

        result = {"elements": elements, "image_width": W, "image_height": H, "latency_ms": elapsed}

        # Optional: draw clean annotation overlay (boxes + bold ID labels)
        if include_annotated:
            from PIL import ImageDraw, ImageFont
            ann = image.copy()
            draw = ImageDraw.Draw(ann)

            # Use a bold font for the ID labels so the model can read them clearly.
            # Try DejaVuSans-Bold first (best readability), fall back to regular, then default.
            label_font = None
            for font_path in [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]:
                try:
                    label_font = ImageFont.truetype(font_path, 14)
                    break
                except Exception:
                    continue
            if label_font is None:
                label_font = ImageFont.load_default()

            # Blue for ID labels — high contrast against most backgrounds
            id_color = (30, 100, 255)  # bright blue
            # Box outline colors per element type
            box_palette = {"icon": (255, 60, 60), "text": (0, 200, 220)}

            for e in elements:
                box_color = box_palette.get(e["type"], (200, 200, 200))
                x1, y1, x2, y2 = e["bbox_pixel"]

                # Draw bounding box (2px width for better visibility)
                draw.rectangle([x1, y1, x2, y2], outline=box_color, width=2)

                # Build label: just the ID number (bold + blue for clarity)
                label = str(e["id"])
                # Get text size for background pill
                bbox = draw.textbbox((0, 0), label, font=label_font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                lx = x1 + 2
                ly = max(y1 - th - 4, 0)

                # Draw a small white background pill behind the label for contrast
                draw.rectangle([lx - 1, ly - 1, lx + tw + 3, ly + th + 2],
                               fill=(255, 255, 255, 220), outline=id_color, width=1)
                draw.text((lx + 1, ly), label, fill=id_color, font=label_font)

            buf = io.BytesIO(); ann.save(buf, format="PNG")
            result["annotated_image_base64"] = base64.b64encode(buf.getvalue()).decode()

        os.unlink(temp_path)
        return result

    @modal.fastapi_endpoint(method="GET")
    async def health(self):
        return {"status": "ok", "model": "OmniParser-v2.0"}