"""
OmniParser V2 Client — calls the Modal GPU endpoint.

Usage:
    from omni_parser_client import parse_screenshot, parse_screenshot_b64

    result = parse_screenshot("screenshot.png")
    for e in result.elements:
        print(e.type, e.bbox_pixel, e.center_pixel, e.content)

    result.save_annotated("annotated.png")   # if include_annotated=True
"""

import base64, io, time
from dataclasses import dataclass, field
import os

import requests
from PIL import Image

# ── Endpoint URLs (from .env or fallback) ────────────────────────────────────
MODAL_PARSE_URL = os.getenv("OMNIPARSER_PARSE_URL", "https://ppbhatt500--omniparser-v2-omniparserv2-parse.modal.run")
MODAL_HEALTH_URL = os.getenv("OMNIPARSER_HEALTH_URL", "https://ppbhatt500--omniparser-v2-omniparserv2-health.modal.run")
REQUEST_TIMEOUT = 300


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class UIElement:
    """A single detected UI element (icon or text)."""
    id: int
    type: str                    # "icon" | "text"
    content: str                 # OCR text (empty for icons)
    bbox_pixel: list[int]        # [x1, y1, x2, y2] in pixels
    center_pixel: list[int]      # [cx, cy] in pixels
    interactable: bool


@dataclass
class ParseResult:
    """Full OmniParser response."""
    elements: list[UIElement] = field(default_factory=list)
    image_width: int = 0
    image_height: int = 0
    annotated_image_base64: str = ""
    latency_ms: int = 0

    @property
    def icons(self) -> list[UIElement]:
        return [e for e in self.elements if e.type == "icon"]

    @property
    def texts(self) -> list[UIElement]:
        return [e for e in self.elements if e.type == "text"]

    def save_annotated(self, path: str):
        """Save the annotated overlay image to disk."""
        if not self.annotated_image_base64:
            print("[omniparser] No annotated image (request with include_annotated=True)")
            return
        Image.open(io.BytesIO(base64.b64decode(self.annotated_image_base64))).save(path)
        print(f"[omniparser] Annotated image saved → {path}")

    def find_by_text(self, query: str) -> list[UIElement]:
        """Case-insensitive search across text elements."""
        q = query.lower()
        return [e for e in self.elements if q in e.content.lower()]


# ── Public API ───────────────────────────────────────────────────────────────

def parse_screenshot(
    image_path: str,
    box_threshold: float = 0.05,
    iou_threshold: float = 0.1,
    imgsz: int = 640,
    include_annotated: bool = True,
) -> ParseResult:
    """Parse a screenshot file → detected UI elements."""
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()
    return _parse(image_b64, box_threshold, iou_threshold, imgsz, include_annotated)


def parse_screenshot_b64(
    image_b64: str,
    box_threshold: float = 0.05,
    iou_threshold: float = 0.1,
    imgsz: int = 640,
    include_annotated: bool = False,
) -> ParseResult:
    """Parse a base64-encoded screenshot → detected UI elements."""
    # Strip data-URI prefix if present
    if image_b64.startswith("data:image/"):
        image_b64 = image_b64.split(",", 1)[1]
    return _parse(image_b64, box_threshold, iou_threshold, imgsz, include_annotated)


def health_check() -> dict:
    """Ping the Modal endpoint."""
    resp = requests.get(MODAL_HEALTH_URL, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── Internals ────────────────────────────────────────────────────────────────

def _parse(image_b64: str, box_threshold: float, iou_threshold: float,
           imgsz: int, include_annotated: bool) -> ParseResult:
    """Shared parse logic — builds payload, calls endpoint, hydrates result."""
    payload = {
        "image_base64": image_b64,
        "box_threshold": box_threshold,
        "iou_threshold": iou_threshold,
        "imgsz": imgsz,
        "include_annotated": include_annotated,
    }
    data = _post_with_retry(MODAL_PARSE_URL, payload)

    elements = [
        UIElement(
            id=e["id"], type=e["type"], content=e.get("content", ""),
            bbox_pixel=e["bbox_pixel"], center_pixel=e["center_pixel"],
            interactable=e.get("interactable", False),
        )
        for e in data.get("elements", [])
    ]
    return ParseResult(
        elements=elements,
        image_width=data.get("image_width", 0),
        image_height=data.get("image_height", 0),
        annotated_image_base64=data.get("annotated_image_base64", ""),
        latency_ms=data.get("latency_ms", 0),
    )


def _post_with_retry(url: str, payload: dict, max_retries: int = 5) -> dict:
    """POST with exponential backoff (handles cold-start delays)."""
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
            if attempt == max_retries:
                raise
            _backoff(attempt, "connection error (container may be cold-starting)")
        except requests.exceptions.HTTPError:
            if resp.status_code in (500, 502, 503, 504) and attempt < max_retries:
                _backoff(attempt, f"HTTP {resp.status_code}")
            else:
                print(f"[omniparser] FAILED ({resp.status_code}): {resp.text[:300]}")
                raise
    raise RuntimeError("Unreachable")


def _backoff(attempt: int, reason: str):
    wait = min(5 * attempt, 30)
    print(f"[omniparser] attempt {attempt} — {reason}, retrying in {wait}s")
    time.sleep(wait)


# ── CLI test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python omni_parser_client.py <screenshot.png>")
        sys.exit(1)

    result = parse_screenshot(sys.argv[1], include_annotated=True)
    print(f"\n{result.image_width}x{result.image_height} — "
          f"{len(result.elements)} elements ({len(result.icons)} icons, "
          f"{len(result.texts)} text) — {result.latency_ms}ms\n")
    for e in result.elements:
        tag = "ICON" if e.type == "icon" else "TEXT"
        print(f"  [{tag:4}] id={e.id:<3} bbox={e.bbox_pixel} center={e.center_pixel}"
              f"{'  | ' + e.content if e.content else ''}")
    result.save_annotated("annotated_output.png")