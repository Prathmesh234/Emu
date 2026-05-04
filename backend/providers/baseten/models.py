"""Curated 200B+ vision-capable model options for Baseten."""

MODEL_OPTIONS = [
    {
        "id": "meta-llama/Llama-4-Maverick-17B-128E-Instruct",
        "label": "Llama 4 Maverick",
        "description": "400B-parameter multimodal model; Baseten served model names can vary by deployment.",
        "parameters": "400B",
        "vision": True,
        "source": "Baseten",
    },
]


def get_model_options():
    return MODEL_OPTIONS
