"""
OpenAI-compatible provider — vLLM, SGLang, Ollama, or any OpenAI-compat server.

Public API:
    from providers.openai_compatible import call_model, is_ready, ensure_ready
"""

from providers.openai_compatible.client import call_model, is_ready, ensure_ready

__all__ = ["call_model", "is_ready", "ensure_ready"]
