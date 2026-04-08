"""
Amazon Bedrock provider — uses AWS Bedrock-hosted models.

Public API:
    from providers.bedrock import call_model, is_ready, ensure_ready
"""

from providers.bedrock.client import call_model, is_ready, ensure_ready

__all__ = ["call_model", "is_ready", "ensure_ready"]
