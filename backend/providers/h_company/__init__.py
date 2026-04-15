"""
H Company (Holo) provider — holo3-35b-a3b via OpenAI-compatible API.

Public API:
    from providers.h_company import call_model, is_ready, ensure_ready
"""

from providers.h_company.client import call_model, is_ready, ensure_ready

__all__ = ["call_model", "is_ready", "ensure_ready"]
