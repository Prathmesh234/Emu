"""
Baseten provider — OpenAI-compatible inference via Baseten.

Public API:
    from providers.baseten import call_model, is_ready, ensure_ready
"""

from providers.baseten.client import call_model, is_ready, ensure_ready

__all__ = ["call_model", "is_ready", "ensure_ready"]
