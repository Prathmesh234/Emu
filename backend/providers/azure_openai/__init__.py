"""
Azure OpenAI provider — uses Azure-hosted OpenAI models.

Public API:
    from providers.azure_openai import call_model, is_ready, ensure_ready
"""

from providers.azure_openai.client import call_model, is_ready, ensure_ready

__all__ = ["call_model", "is_ready", "ensure_ready"]
