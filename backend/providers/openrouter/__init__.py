"""
OpenRouter provider — routes to 200+ models via a single API.

Public API:
    from providers.openrouter import call_model, is_ready, ensure_ready
"""

from providers.openrouter.client import call_model, is_ready, ensure_ready

__all__ = ["call_model", "is_ready", "ensure_ready"]
