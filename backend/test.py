"""
Quick test: send a screenshot + system prompt to the deployed Qwen3.5 VLM on Modal.
Usage:
    uv run python test.py
    uv run python test.py --image path/to/screenshot.png
    uv run python test.py --task "open the browser"
"""

import argparse
import base64
import os
import sys
import time
from pathlib import Path

import requests

from prompts.system_prompt import SYSTEM_PROMPT

# --- Configuration ---
MODAL_URL = "https://ppbhatt500--qwen35-35b-a3b-vlm-qwen35vlm.us-east.modal.direct"
SCREENSHOT_DIR = Path(__file__).parent / "emulation_screen_shots"


def get_latest_screenshot(directory: Path) -> Path:
    """Return the most recent .png file in the directory."""
    pngs = sorted(directory.glob("*.png"), key=os.path.getmtime, reverse=True)
    if not pngs:
        print(f"No screenshots found in {directory}")
        sys.exit(1)
    return pngs[0]


def encode_image(image_path: Path) -> str:
    """Read an image and return a base64 data URI."""
    data = image_path.read_bytes()
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def send_request(image_uri: str, task: str) -> None:
    """Send the screenshot + system prompt + task to the Modal endpoint and stream the response."""
    payload = {
        "model": "Qwen/Qwen3.5-35B-A3B",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_uri}},
                    {"type": "text", "text": task},
                ],
            },
        ],
        "max_tokens": 1024,
        "temperature": 0.6,
    }

    print(f"POST {MODAL_URL}/v1/chat/completions")
    print(f"Task: {task}")
    print("---")

    # Retry loop — container may be cold-starting (MIN_CONTAINERS=0)
    max_retries = 10
    for attempt in range(1, max_retries + 1):
        try:
            print(f"Attempt {attempt}/{max_retries}...", end=" ", flush=True)
            resp = requests.post(
                f"{MODAL_URL}/v1/chat/completions",
                json=payload,
                timeout=300,
            )
            resp.raise_for_status()
            print("OK")
            break
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
            if attempt == max_retries:
                print("FAILED")
                raise
            wait = min(5 * attempt, 30)
            print(f"retrying in {wait}s (container likely cold-starting)")
            time.sleep(wait)
        except requests.exceptions.HTTPError:
            if resp.status_code in (500, 502, 503, 504) and attempt < max_retries:
                wait = min(5 * attempt, 30)
                print(f"{resp.status_code} — retrying in {wait}s")
                time.sleep(wait)
            else:
                print(f"FAILED ({resp.status_code})")
                print(resp.text[:500])
                raise

    data = resp.json()
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}

    reasoning = message.get("reasoning_content") or ""
    content = message.get("content") or ""

    if reasoning:
        print("=== Reasoning ===")
        print(reasoning)
        print()

    print("=== Response ===")
    print(content)


def main():
    parser = argparse.ArgumentParser(description="Test Qwen3.5 VLM on Modal")
    parser.add_argument(
        "--image",
        type=str,
        default=None,
        help="Path to screenshot image (default: latest in emulation_screen_shots/)",
    )
    parser.add_argument(
        "--task",
        type=str,
        default="Point to the RIVER_project folder",
        help="Task instruction for the agent",
    )
    args = parser.parse_args()

    # Resolve image path
    if args.image:
        img_path = Path(args.image)
    else:
        img_path = get_latest_screenshot(SCREENSHOT_DIR)

    print(f"Image: {img_path.name}")
    image_uri = encode_image(img_path)

    send_request(image_uri, args.task)


if __name__ == "__main__":
    main()
