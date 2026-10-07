import pytest

from imobhunter.sources.registry import SourceRegistry, build_default_registry
from imobhunter.sources.stub import ConfiguredSourceStub

def test_default_registry_contains_core_sources():
    ids = {source.source_id for source in build_default_registry().all()}
    assert {"ibge_cnefe", "sinter_cib", "geosampa", "sicar", "osm"} <= ids

def test_registry_rejects_duplicate_source():
    registry = SourceRegistry({})
    source = ConfiguredSourceStub("x", "X", "test")
    registry.register(source)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(source)
