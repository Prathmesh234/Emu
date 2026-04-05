"""
OpenAI provider — GPT-4o / GPT-4.1 for desktop automation.

Public API:
    from providers.openai_provider import call_model, is_ready, ensure_ready
"""

from providers.openai_provider.client import call_model, is_ready, ensure_ready

__all__ = ["call_model", "is_ready", "ensure_ready"]
