"""Curated 200B+ vision-capable model options for Together AI."""

MODEL_OPTIONS = [
    {
        "id": "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
        "label": "Llama 4 Maverick FP8",
        "description": "400B-parameter multimodal Llama 4 Maverick endpoint on Together AI.",
        "parameters": "400B",
        "vision": True,
        "source": "Together AI",
    },
]


def get_model_options():
    return MODEL_OPTIONS
