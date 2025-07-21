import yaml
from pydantic import TypeAdapter
from typing import Dict, List
from pathlib import Path
from alertissimo.core.schema import Capability

def load_broker_registry_from_yaml() -> Dict[str, List[Capability]]:
    registry_path = Path(__file__).parent.parent / "core" / "brokers" / "registry" / "capabilities.yaml"
    registry_path = Path(__file__).parent / "capabilities.yaml"
    with open(registry_path, "r") as f:
        raw_data = yaml.safe_load(f)
        adapter = TypeAdapter(Dict[str, List[Capability]])
        return adapter.validate_python({
            broker: caps["capabilities"]
            for broker, caps in raw_data.items()
        })
    return errors

BROKER_FIELDS = {"source", "sources"}  # any fields expecting Source(s)
BROKER_REGISTRY = load_broker_registry_from_yaml()
ALL_BROKERS = list(BROKER_REGISTRY.keys())  # Get all broker names
