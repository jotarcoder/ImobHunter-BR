from dataclasses import dataclass

from .base import SourceAdapter
from .geosampa import GeoSampaAdapter
from .stub import ConfiguredSourceStub


@dataclass
class SourceRegistry:
    _sources: dict[str, SourceAdapter]

    def register(self, source: SourceAdapter) -> None:
        if source.source_id in self._sources:
            raise ValueError(f"source already registered: {source.source_id}")
        self._sources[source.source_id] = source

    def get(self, source_id: str) -> SourceAdapter | None:
        return self._sources.get(source_id)

    def all(self) -> list[SourceAdapter]:
        return list(self._sources.values())


def build_default_registry() -> SourceRegistry:
    registry = SourceRegistry({})
    registry.register(GeoSampaAdapter())

    sources = [
        ("ibge_cnefe", "IBGE / CNEFE", "address"),
        ("sinter_cib", "SINTER / CIB", "national_cadastre"),
        ("municipal", "Municipal geoservices", "municipal"),
        ("cnpj", "Receita Federal / CNPJ", "company"),
        ("sncr", "INCRA / SNCR", "rural"),
        ("sicar", "SICAR / CAR", "environmental"),
        ("sigef", "SIGEF", "rural"),
        ("inde", "INDE", "geospatial"),
        ("icmbio", "ICMBio", "environmental"),
        ("iphan", "IPHAN", "heritage"),
        ("osm", "OpenStreetMap", "geospatial"),
    ]
    for source_id, name, category in sources:
        registry.register(ConfiguredSourceStub(source_id, name, category))
    return registry
