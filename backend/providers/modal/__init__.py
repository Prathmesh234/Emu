"""
Modal provider — GPU inference via deployed Qwen3.5 VLM on Modal.

Public API:
    from providers.modal import call_model, is_ready, ensure_ready
"""

from providers.modal.client import call_modal as call_model
from providers.modal.health import is_ready, ensure_ready

__all__ = ["call_model", "is_ready", "ensure_ready"]
