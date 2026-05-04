"""Curated model options for OpenAI-compatible endpoints.

Custom endpoints expose deployment-specific model names, so the strict catalog
does not assume any shared 200B+ vision model id.
"""

MODEL_OPTIONS = []


def get_model_options():
    return MODEL_OPTIONS
