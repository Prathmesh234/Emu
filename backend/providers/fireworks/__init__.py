"""
Fireworks AI provider — fast inference via Fireworks.

Public API:
    from providers.fireworks import call_model, is_ready, ensure_ready
"""

from providers.fireworks.client import call_model, is_ready, ensure_ready

__all__ = ["call_model", "is_ready", "ensure_ready"]
