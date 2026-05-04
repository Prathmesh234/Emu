"""Curated model options for Modal.

Modal runs whatever local deployment the project starts. The strict dropdown
catalog remains empty because there is no single provider-level 200B+ vision
model identifier to select safely.
"""

MODEL_OPTIONS = []


def get_model_options():
    return MODEL_OPTIONS
