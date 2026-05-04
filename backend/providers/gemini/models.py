"""Curated model options for Gemini.

The chat dropdown only lists models with a published 200B+ parameter count and
vision support. Google does not publish Gemini parameter counts, so the strict
catalog is intentionally empty.
"""

MODEL_OPTIONS = []


def get_model_options():
    return MODEL_OPTIONS
