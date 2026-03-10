"""
health.py — Modal container health check

Ensures the SGLang server inside the Modal container is fully ready
before we send the first inference request.

Usage:
    from providers.modal import is_ready, ensure_ready

    ensure_ready()   # blocks until the container responds, or raises
"""

import time
import os
import requests

MODAL_URL = os.getenv("MODAL_VLM_URL", "https://ppbhatt500--qwen35-35b-a3b-vlm-qwen35vlm.us-east.modal.direct")
HEALTH_ENDPOINT = f"{MODAL_URL}/health"
MODELS_ENDPOINT = f"{MODAL_URL}/v1/models"

# State
_ready = False


def is_ready() -> bool:
    """Quick non-blocking check. Returns True if container has been confirmed ready."""
    return _ready


def ensure_ready(
    timeout: int = 300,
    poll_interval: int = 5,
    verbose: bool = True,
) -> None:
    """
    Block until the Modal container is healthy and serving.

    Polls the /health endpoint repeatedly. Once it returns 200,
    also verifies /v1/models responds (SGLang is loaded and ready).

    Args:
        timeout:       Max seconds to wait before giving up.
        poll_interval: Seconds between retries.
        verbose:       Print progress to stdout.

    Raises:
        TimeoutError: If the container is not ready within `timeout` seconds.
    """
    global _ready

    if _ready:
        return

    if verbose:
        print("[modal_health] Checking if Modal container is ready...")

    deadline = time.time() + timeout
    attempt = 0

    while time.time() < deadline:
        attempt += 1
        try:
            # Step 1: basic health check
            resp = requests.get(HEALTH_ENDPOINT, timeout=10)
            resp.raise_for_status()

            # Step 2: verify model is loaded
            resp2 = requests.get(MODELS_ENDPOINT, timeout=10)
            resp2.raise_for_status()
            models = resp2.json().get("data", [])

            if models:
                _ready = True
                if verbose:
                    model_ids = [m.get("id", "?") for m in models]
                    print(f"[modal_health] Container ready! Models: {model_ids}")
                return

            if verbose:
                print(f"[modal_health] attempt {attempt}: /health OK but no models loaded yet, retrying in {poll_interval}s...")

        except requests.exceptions.ConnectionError:
            if verbose:
                print(f"[modal_health] attempt {attempt}: connection refused (container starting), retrying in {poll_interval}s...")
        except requests.exceptions.Timeout:
            if verbose:
                print(f"[modal_health] attempt {attempt}: timeout (container cold-starting), retrying in {poll_interval}s...")
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            if verbose:
                print(f"[modal_health] attempt {attempt}: HTTP {status}, retrying in {poll_interval}s...")
        except Exception as e:
            if verbose:
                print(f"[modal_health] attempt {attempt}: {type(e).__name__}: {e}, retrying in {poll_interval}s...")

        time.sleep(poll_interval)

    raise TimeoutError(
        f"[modal_health] Container not ready after {timeout}s ({attempt} attempts). "
        "Is the Modal app deployed?"
    )
