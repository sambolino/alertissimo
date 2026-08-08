from pathlib import Path
import yaml

ROOT=Path('alertissimo/core/brokers/registry')
TARGETS=[(b,o) for b in ('fink','alerce','antares') for o in ('ztf','lsst')]

def test_registry_contracts():
    assert not ROOT.joinpath('feature_catalog.yaml').read_text().lstrip().startswith('records:')
    for b,o in TARGETS:
        endpoints=yaml.safe_load((ROOT/b/o/'endpoints.yaml').read_text())['endpoints']
        mappings=yaml.safe_load((ROOT/b/o/'mappings.yaml').read_text())
        for endpoint in endpoints.values():
            assert {'enabled','status','transport','output','capabilities'} <= endpoint.keys()
            assert not {'provides','output_type','semantic_fields'} & endpoint.keys()
        assert {'sources','mappings'} <= mappings.keys()
        for source in mappings['sources'].values(): assert set(source['endpoints']) <= set(endpoints)
    assert (ROOT/'unmapped_fields.yaml').exists()
    assert (ROOT/'mapping_refactor_report.md').exists()
