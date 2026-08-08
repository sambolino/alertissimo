from pathlib import Path
from alertissimo.core.brokers.registry.validate_semantic_paths import validate_file

ROOT=Path('alertissimo/core/brokers/registry')
def test_paths_pass_conservative_guardrails():
    for broker in ('fink','alerce','antares'):
        for path in (ROOT/broker).glob('*/mappings.yaml'):
            assert validate_file(path)==[]
