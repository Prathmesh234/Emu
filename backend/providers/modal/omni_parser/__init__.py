"""
OmniParser V2 — UI element detection via Modal GPU.

Submodules:
    deploy.py  — Modal deployment definition (modal deploy deploy.py)
    client.py  — Python client to call the deployed endpoint
"""

from providers.modal.omni_parser.client import (
    parse_screenshot,
    parse_screenshot_b64,
    health_check,
    ParseResult,
    UIElement,
)

__all__ = [
    "parse_screenshot",
    "parse_screenshot_b64",
    "health_check",
    "ParseResult",
    "UIElement",
]
