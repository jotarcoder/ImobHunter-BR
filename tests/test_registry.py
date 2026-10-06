from imobhunter.sources.registry import build_default_registry

def test_default_registry_contains_core_sources():
    ids = {source.source_id for source in build_default_registry().all()}
    assert {"ibge_cnefe", "sinter_cib", "geosampa", "sicar", "osm"} <= ids
