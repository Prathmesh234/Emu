"""
providers/registry.py — Auto-detect and load the active inference provider.

Checks environment variables in priority order and loads the matching
provider module. All providers expose the same three-function interface:

    call_model(agent_req: AgentRequest) -> AgentResponse
    is_ready() -> bool
    ensure_ready(**kwargs) -> None

Detection order:
    1. EMU_PROVIDER env var (explicit override)
    2. ANTHROPIC_API_KEY  → Claude
    3. OPENROUTER_API_KEY → OpenRouter (200+ models)
    4. OPENAI_API_KEY     → OpenAI  (unless OPENAI_BASE_URL is also set)
    5. OPENAI_BASE_URL    → OpenAI-compatible (vLLM, SGLang, Ollama, etc.)
    6. GOOGLE_API_KEY     → Google Gemini
    7. Modal fallback     → Modal GPU (no key needed)
"""

import os
import importlib

# Provider module paths keyed by short name
_PROVIDER_MAP = {
    "claude":          "providers.claude",
    "openai":          "providers.openai_provider",
    "openrouter":      "providers.openrouter",
    "gemini":          "providers.gemini",
    "openai_compatible": "providers.openai_compatible",
    "modal":           "providers.modal",
}


def _detect_provider() -> str:
    """Return the short name of the best available provider."""

    # Explicit override
    explicit = os.environ.get("EMU_PROVIDER", "").strip().lower()
    if explicit and explicit in _PROVIDER_MAP:
        return explicit

    # Auto-detect from API keys
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"

    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"

    if os.environ.get("OPENAI_BASE_URL") and os.environ.get("OPENAI_API_KEY", ""):
        # Custom endpoint — vLLM / SGLang / Ollama / etc.
        return "openai_compatible"

    if os.environ.get("OPENAI_API_KEY"):
        return "openai"

    if os.environ.get("GOOGLE_API_KEY"):
        return "gemini"

    # Fallback
    return "modal"


def load_provider():
    """
    Detect and import the active provider module.

    Returns (call_model, is_ready, ensure_ready, provider_name).
    """
    name = _detect_provider()
    module_path = _PROVIDER_MAP[name]

    print(f"[provider] Loading provider: {name}  (module: {module_path})")
    mod = importlib.import_module(module_path)

    return (
        mod.call_model,
        mod.is_ready,
        mod.ensure_ready,
        name,
    )


def load_compact_provider():
    """
    Load the compact client for the active provider.

    Returns a compact(messages: list[PreviousMessage]) -> str function.
    """
    name = _detect_provider()
    module_path = _PROVIDER_MAP[name]

    compact_module = f"{module_path}.client_compact"
    print(f"[provider] Loading compact client: {name}  (module: {compact_module})")
    mod = importlib.import_module(compact_module)

    return mod.compact
