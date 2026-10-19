from dataclasses import dataclass

from .base import SourceAdapter
from .cnefe import CNEFEAdapter
from .cnir import CNIRAdapter
from .cnpj import CNPJAdapter
from .icmbio import ICMBioAdapter
from .iphan import IPHANAdapter
from .municipal_iptu import MunicipalIPTUAdapter
from .osm import OSMAdapter
from .geosampa import GeoSampaAdapter
from .national_geocoder import NationalAddressGeocoderAdapter
from .sicar import SICARAdapter
from .sigef import SIGEFAdapter
from .sinter import SINTERAdapter
from .sncr import SNCRAdapter
from .stub import ConfiguredSourceStub
from .ogc_wfs import ConfigurableWFSAdapter
from .public_geoservices import PublicGeoservicesAdapter


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
    registry.register(NationalAddressGeocoderAdapter())
    registry.register(CNEFEAdapter())
    registry.register(SINTERAdapter())
    registry.register(SNCRAdapter())
    registry.register(SICARAdapter())
    registry.register(SIGEFAdapter())
    registry.register(CNIRAdapter())
    registry.register(CNPJAdapter())
    registry.register(ICMBioAdapter())
    registry.register(IPHANAdapter())
    registry.register(PublicGeoservicesAdapter())
    registry.register(OSMAdapter())
    registry.register(MunicipalIPTUAdapter())

    registry.register(ConfigurableWFSAdapter())
    registry.register(ConfiguredSourceStub("inde", "INDE catalog", "geospatial"))
    return registry
