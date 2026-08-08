from alertissimo.core.brokers.registry.capability_builder import build

def test_all_targets_build_and_inactive_sources_stay_inactive():
    for broker in ('fink','alerce','antares'):
        for origin in ('ztf','lsst'):
            result=build(broker,origin)
            assert result['broker']==broker
            for field in result['semantic_fields'].values():
                if field['source_status']=='declared_only' or field['endpoint_status']=='known_unsupported':
                    assert not field['active']
