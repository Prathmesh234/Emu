"""Curated 200B+ vision-capable model options for Fireworks AI."""

MODEL_OPTIONS = [
    {
        "id": "accounts/fireworks/models/llama4-maverick-instruct-basic",
        "label": "Llama 4 Maverick",
        "description": "400B-parameter multimodal Llama 4 model served by Fireworks.",
        "parameters": "400B",
        "vision": True,
        "source": "Fireworks",
    },
]


def get_model_options():
    return MODEL_OPTIONS
