"""Curated model options for Anthropic.

The chat dropdown only lists models with a published 200B+ parameter count and
vision support. Anthropic's current model sizes are not published, so the
strict catalog is intentionally empty.
"""

MODEL_OPTIONS = []


def get_model_options():
    return MODEL_OPTIONS
