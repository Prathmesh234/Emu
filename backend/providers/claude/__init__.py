"""
Claude provider — Anthropic Claude API for desktop automation.

Public API:
    from providers.claude import call_model, is_ready, ensure_ready
"""

from providers.claude.client import call_model, is_ready, ensure_ready

__all__ = ["call_model", "is_ready", "ensure_ready"]
