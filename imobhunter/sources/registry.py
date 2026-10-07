from dataclasses import dataclass

from .base import SourceAdapter
from .cnefe import CNEFEAdapter
from .geosampa import GeoSampaAdapter
from .sicar import SICARAdapter
from .sinter import SINTERAdapter
from .sncr import SNCRAdapter
from .stub import ConfiguredSourceStub


@dataclass
class SourceRegistry:
    _sources: dict[str, SourceAdapter]

    def register(self, source: SourceAdapter) -> None:
        if source.source_id in self._sources:
            raise ValueError(f"source already registered: {source.source_id}")

    def get(self, source_id: str) -> SourceAdapter | None:
        return self._sources.get(source_id)

    def all(self) -> list[SourceAdapter]:
        return list(self._sources.values())


def build_default_registry() -> SourceRegistry:
    registry = SourceRegistry({})
    registry.register(GeoSampaAdapter())
    registry.register(CNEFEAdapter())
    registry.register(SINTERAdapter())
    registry.register(SNCRAdapter())
    registry.register(SICARAdapter())

    sources = [
        ("municipal", "Municipal geoservices", "municipal"),
        ("cnpj", "Receita Federal / CNPJ", "company"),
        ("sigef", "SIGEF", "rural"),
        ("inde", "INDE", "geospatial"),
        ("icmbio", "ICMBio", "environmental"),
        ("iphan", "IPHAN", "heritage"),
        ("osm", "OpenStreetMap", "geospatial"),
    ]
    for source_id, name, category in sources:
        registry.register(ConfiguredSourceStub(source_id, name, category))
    return registry
