import httpx

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.public_geoservices import (
    PublicGeoservicesAdapter,
    _coordinates,
    _feature_layers,
)


CAPABILITIES = """<?xml version="1.0"?>
<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0">
  <wfs:FeatureTypeList>
    <wfs:FeatureType><wfs:Name>SICG:Bem_Protecao</wfs:Name><wfs:Title>Bens Materiais Protegidos</wfs:Title></wfs:FeatureType>
    <wfs:FeatureType><wfs:Name>SICG:sitios</wfs:Name><wfs:Title>Sítios Arqueológicos</wfs:Title></wfs:FeatureType>
    <wfs:FeatureType><wfs:Name>ICMBio:uc_federais</wfs:Name><wfs:Title>Unidades de Conservação Federais</wfs:Title></wfs:FeatureType>
  </wfs:FeatureTypeList>
</wfs:WFS_Capabilities>
"""


class FakeGeocoder:
    def geocode(self, _query):
        return {"latitude": -23.56, "longitude": -46.66}


def test_feature_layers_and_layer_selection():
    layers = _feature_layers(CAPABILITIES)
    assert len(layers) == 3
    assert "SICG:Bem_Protecao" in PublicGeoservicesAdapter._select_layers("iphan", layers)
    assert "SICG:sitios" in PublicGeoservicesAdapter._select_layers("iphan", layers)
    assert PublicGeoservicesAdapter._select_layers("icmbio", layers) == ["ICMBio:uc_federais"]


def test_coordinates_for_point_and_polygon():
    assert _coordinates({"type": "Point", "coordinates": [-46.66, -23.56]}) == (-23.56, -46.66)
    lat, lon = _coordinates({"type": "Polygon", "coordinates": [[[-46.7, -23.6], [-46.6, -23.5]]]})
    assert lat == -23.55
    assert round(lon, 2) == -46.65


def test_live_official_geoservices_search_maps_provenance_and_caches(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        params = dict(request.url.params)
        if params.get("request") == "GetCapabilities":
            return httpx.Response(200, text=CAPABILITIES)
        layer = params.get("typeNames")
        if layer == "SICG:Bem_Protecao":
            props = {"id_bem": "IPHAN-7", "nome_bem": "Edifício protegido"}
        elif layer == "SICG:sitios":
            props = {"id_sitio": "IPHAN-8", "nome_sitio": "Sítio arqueológico"}
        elif layer == "ICMBio:uc_federais":
            props = {"cod_uc": "UC-1", "nome_uc": "Parque federal"}
        else:
            return httpx.Response(404)
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "id": f"{layer}.1",
                "geometry": {"type": "Point", "coordinates": [-46.66, -23.56]},
                "properties": props,
            }],
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = PublicGeoservicesAdapter(
        cache_dir=tmp_path / "cache",
        client=client,
        geocoder=FakeGeocoder(),
    )
    records = adapter.search(SearchRequest(
        address="Rua Pamplona", number="1578", city="São Paulo", state="SP"
    ))

    assert len(records) == 3
    assert {r.attributes["official_source"] for r in records} == {"IPHAN", "ICMBio / INDE"}
    assert all(r.latitude == -23.56 and r.longitude == -46.66 for r in records)
    assert all(r.provenance[0].source_id == "official_geo_overlays" for r in records)
    assert any(r.attributes["overlay_type"] == "heritage" for r in records)
    assert any(r.attributes["overlay_type"] == "conservation_unit" for r in records)
    assert any(req.url.host in {"geoserver.iphan.gov.br", "geoservicos.inde.gov.br"} for req in calls)
    client.close()


def test_overlay_returns_no_results_when_address_context_is_missing(tmp_path):
    adapter = PublicGeoservicesAdapter(cache_dir=tmp_path / "cache", geocoder=FakeGeocoder())
    assert adapter.search(SearchRequest(address="Rua Pamplona")) == []


def test_status_explains_live_public_sources(tmp_path):
    status = PublicGeoservicesAdapter(cache_dir=tmp_path / "cache").status()
    assert status.status == "available"
    assert "IPHAN" in status.message
    assert "ICMBio" in status.message
