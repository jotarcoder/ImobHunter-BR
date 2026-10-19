import httpx

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.national_municipal_cadastre import (
    NationalMunicipalCadastreAdapter,
    _official_endpoint,
    _wfs_endpoint,
    _representative_point,
)

CSW = """<?xml version="1.0"?>
<csw:GetRecordsResponse xmlns:csw="http://www.opengis.net/cat/csw/2.0.2">
  <csw:SearchResults>
    <csw:Record>
      <dc:identifier xmlns:dc="http://purl.org/dc/elements/1.1/">muni-cadastre-1</dc:identifier>
      <dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">Cadastro imobiliário municipal — Município de Teste, SP — lotes urbanos</dc:title>
      <dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">Prefeitura Municipal</dc:creator>
      <dc:subject xmlns:dc="http://purl.org/dc/elements/1.1/">quadra; lote; cadastro territorial</dc:subject>
      <dct:references xmlns:dct="http://purl.org/dc/terms/" scheme="WFS">https://cadastro.exemplo.gov.br/geoserver/ows</dct:references>
    </csw:Record>
  </csw:SearchResults>
</csw:GetRecordsResponse>
"""

CAPABILITIES = """<?xml version="1.0"?>
<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0">
  <wfs:FeatureTypeList>
    <wfs:FeatureType>
      <wfs:Name>cadastro:lotes_urbanos</wfs:Name>
      <wfs:Title>Lotes urbanos e quadras fiscais</wfs:Title>
    </wfs:FeatureType>
    <wfs:FeatureType>
      <wfs:Name>cadastro:ruas</wfs:Name>
      <wfs:Title>Eixos viários</wfs:Title>
    </wfs:FeatureType>
  </wfs:FeatureTypeList>
</wfs:WFS_Capabilities>
"""


class FakeGeocoder:
    def geocode(self, _query):
        return {"latitude": -23.56, "longitude": -46.66}


def test_only_https_government_hosts_are_queried():
    assert _official_endpoint("https://cadastro.exemplo.gov.br/geoserver/ows")
    assert not _official_endpoint("http://cadastro.exemplo.gov.br/geoserver/ows")
    assert not _official_endpoint("https://random.example/geoserver/ows")
    assert _wfs_endpoint("https://cadastro.exemplo.gov.br/geoserver/ows")
    assert not _wfs_endpoint("https://cadastro.exemplo.gov.br/geoserver/wms")


def test_representative_point_supports_polygon_geometry():
    lat, lon = _representative_point({
        "type": "Polygon",
        "coordinates": [[[-46.7, -23.6], [-46.6, -23.5], [-46.7, -23.6]]],
    })
    assert lat == -23.566666666666666
    assert lon == -46.666666666666664


def test_discovers_official_municipal_wfs_and_returns_polygon_with_provenance(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST":
            query_text = request.content.decode("utf-8").casefold()
            assert "município de teste" in query_text or "municipio de teste" in query_text
            return httpx.Response(200, text=CSW)
        params = dict(request.url.params)
        if params.get("request") == "GetCapabilities":
            return httpx.Response(200, text=CAPABILITIES)
        assert params.get("typeNames") == "cadastro:lotes_urbanos"
        assert params.get("bbox")
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "id": "lote.42",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-46.661, -23.561], [-46.659, -23.561],
                                     [-46.659, -23.559], [-46.661, -23.561]]],
                },
                "properties": {
                    "id_lote": "42",
                    "quadra": "07",
                    "lote": "42",
                    "area_m2": "350.5",
                    "logradouro": "Rua Exemplo",
                    "inscricao_imobiliaria": "123.456.789",
                },
            }],
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = NationalMunicipalCadastreAdapter(
        cache_dir=tmp_path / "cache", client=client, geocoder=FakeGeocoder()
    )
    records = adapter.search(SearchRequest(
        address="Rua Exemplo", number="42", city="Município de Teste", state="SP"
    ))

    assert len(records) == 1
    record = records[0]
    assert record.property_id == "lote.42"
    assert record.block == "07"
    assert record.lot == "42"
    assert record.area_m2 == 350.5
    assert record.attributes["cadastre_match"] == "spatial_candidate_only"
    assert record.attributes["sql_status"] == "not_provided_by_layer"
    assert record.attributes["iptu_status"] == "not_provided_by_layer"
    assert record.attributes["owner_status"] == "not_provided_by_layer"
    assert record.attributes["geometry_geojson"].startswith('{"type": "Polygon"')
    assert record.provenance[0].source_id == "national_municipal_cadastre"
    assert any(req.method == "POST" for req in calls)
    client.close()


def test_missing_address_context_skips_network(tmp_path):
    adapter = NationalMunicipalCadastreAdapter(
        cache_dir=tmp_path / "cache", geocoder=FakeGeocoder()
    )
    assert adapter.search(SearchRequest(address="Rua Exemplo")) == []
