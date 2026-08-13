"""Canonical filesystem paths for data-layer resources."""

from pathlib import Path


DATA_LAYER_ROOT = Path(__file__).parent
PROVIDERS_ROOT = DATA_LAYER_ROOT / "providers"
SEMANTIC_MODEL_ROOT = DATA_LAYER_ROOT / "semantic_model"
ONTOLOGY_PATH = SEMANTIC_MODEL_ROOT / "ontology.yaml"
