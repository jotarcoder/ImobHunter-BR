import json

import httpx

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.official_municipal_services import (
    MUNICIPAL_WFS,
    RIO_ARCGIS_LAYER,
    OfficialMunicipalServicesAdapter,
    _official_url,
)


class FakeGeocoder:
    def geocode(self, _query):
        return {"latitude": -19.9227, "longitude": -43.9451}


CAPABILITIES = """<?xml version="1.0"?>
<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0">
  <wfs:FeatureTypeList>
    <wfs:FeatureType>
      <wfs:Name>cadastro:lotes</wfs:Name>
      <wfs:Title>Lotes e quadras cadastrais</wfs:Title>
    </wfs:FeatureType>
    <wfs:FeatureType>
      <wfs:Name>base:ruas</wfs:Name>
      <wfs:Title>Eixos de vias</wfs:Title>
    </wfs:FeatureType>
  </wfs:FeatureTypeList>
</wfs:WFS_Capabilities>
"""


def test_official_endpoints_are_https_government_domains():
    assert _official_url("https://bhmap.pbh.gov.br/v2/api/idebhgeo/wfs")
    assert _official_url("https://pgeo3.rio.rj.gov.br/arcgis/rest/services")
    assert not _official_url("http://bhmap.pbh.gov.br/wfs")
    assert not _official_url("https://example.com/wfs")


def test_known_wfs_municipal_services_are_configured():
    assert MUNICIPAL_WFS[("praia grande", "sp")]["url"].endswith("/wfs")
    assert MUNICIPAL_WFS[("belo horizonte", "mg")]["url"] == (
        "https://bhmap.pbh.gov.br/v2/api/idebhgeo/wfs"
    )


def test_belo_horizonte_wfs_returns_geometry_quadra_lote_and_sql(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if params.get("request") == "GetCapabilities":
            return httpx.Response(200, text=CAPABILITIES)
        assert params.get("typeNames") == "cadastro:lotes"
        assert params.get("bbox", "").endswith("EPSG:4326")
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "id": "lotes.7",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-43.946, -19.923], [-43.944, -19.923],
                        [-43.944, -19.922], [-43.946, -19.923],
                    ]],
                },
                "properties": {
                    "quadra": "07",
                    "lote": "42",
                    "area_terreno": "350.5",
                    "inscricao_imobiliaria": "123456789",
                },
            }],
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(
        cache_dir=tmp_path / "cache", client=client, geocoder=FakeGeocoder()
    )
    records = adapter.search(SearchRequest(
        address="Rua da Bahia", number="1000", city="Belo Horizonte", state="MG"
    ))
    client.close()

    assert len(records) == 1
    record = records[0]
    assert record.city == "Belo Horizonte"
    assert record.state == "MG"
    assert record.block == "07"
    assert record.lot == "42"
    assert record.area_m2 == 350.5
    assert record.attributes["sql"] == "123456789"
    assert record.attributes["sql_status"] == "provided_by_layer"
    assert json.loads(record.attributes["geometry_geojson"])["type"] == "Polygon"


def test_rio_arcgis_rest_maps_lot_geometry_and_fields(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        expected_path = RIO_ARCGIS_LAYER.removeprefix("https://pgeo3.rio.rj.gov.br")
        assert request.url.path == expected_path + "/query"
        params = dict(request.url.params)
        assert params["geometryType"] == "esriGeometryPoint"
        assert params["outSR"] == "4326"
        return httpx.Response(200, json={
            "features": [{
                "attributes": {
                    "objectid": 77,
                    "inscricao_imobiliaria": "RJ-123",
                    "quadra": "Q-2",
                    "lote": "L-9",
                    "area_descrita": 420,
                },
                "geometry": {
                    "rings": [[
                        [-43.20, -22.90], [-43.19, -22.90],
                        [-43.19, -22.89], [-43.20, -22.90],
                    ]],
                },
            }],
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(
        cache_dir=tmp_path / "cache", client=client, geocoder=FakeGeocoder()
    )
    records = adapter.search(SearchRequest(
        address="Avenida Rio Branco", number="1", city="Rio de Janeiro", state="RJ"
    ))
    client.close()

    assert len(records) == 1
    record = records[0]
    assert record.city == "Rio de Janeiro"
    assert record.state == "RJ"
    assert record.block == "Q-2"
    assert record.lot == "L-9"
    assert record.area_m2 == 420
    assert record.attributes["sql"] == "RJ-123"
    assert record.attributes["service_type"] == "ArcGIS REST"
    assert json.loads(record.attributes["geometry_geojson"])["type"] == "Polygon"


def test_service_failure_is_exposed_in_status(tmp_path):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(
        cache_dir=tmp_path / "cache", client=client, geocoder=FakeGeocoder()
    )
    assert adapter.search(SearchRequest(
        address="Rua da Bahia", number="1000", city="Belo Horizonte", state="MG"
    )) == []
    client.close()
    assert "Belo Horizonte" in (adapter.status().message or "")
    assert "HTTPStatusError" in (adapter.status().message or "")
