"""
Gemini provider — Google Gemini for desktop automation.

Public API:
    from providers.gemini import call_model, is_ready, ensure_ready
"""

from providers.gemini.client import call_model, is_ready, ensure_ready

__all__ = ["call_model", "is_ready", "ensure_ready"]
