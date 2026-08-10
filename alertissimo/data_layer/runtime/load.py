import yaml
#from pydantic import TypeAdapter
from typing import Dict, List
from pathlib import Path

def load_broker_registry_from_yaml() -> Dict[str, List[str]]:
    """Load broker capabilities from YAML file as simple strings"""
    possible_paths = [Path(__file__).parent / "capabilities.yaml"]

    for path in possible_paths:
        if path.exists():
            with open(path, "r") as f:
                raw_data = yaml.safe_load(f)

                # Handle both formats: list or dict with 'capabilities' key
                result = {}
                for broker, caps in raw_data.items():
                    if isinstance(caps, dict) and 'capabilities' in caps:
                        result[broker] = caps['capabilities']
                    elif isinstance(caps, list):
                        result[broker] = caps
                    else:
                        result[broker] = []

                return result

    # Return empty dict if no file found (for tests)
    print(f"Warning: No capabilities.yaml found in {possible_paths}")
    return {}


# Global registry - simple dict of broker → list of capability strings
BROKER_REGISTRY = load_broker_registry_from_yaml()
ALL_BROKERS = list(BROKER_REGISTRY.keys())

# Fields that expect Source objects
BROKER_FIELDS = {"source", "sources"}
