"""
Together AI provider — fast open-source model inference.

Public API:
    from providers.together_ai import call_model, is_ready, ensure_ready
"""

from providers.together_ai.client import call_model, is_ready, ensure_ready

__all__ = ["call_model", "is_ready", "ensure_ready"]
