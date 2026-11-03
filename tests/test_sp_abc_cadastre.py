"""Santo André/Jundiaí public WFS cannot be misrepresented as fiscal SQL."""
import json

import httpx

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.official_municipal_services import OfficialMunicipalServicesAdapter
from imobhunter.sources.sp_abc_cadastre import (
    JUNDIAI_LAYER, JUNDIAI_PORTAL, JUNDIAI_WFS,
    SANTO_ANDRE_PORTAL, SANTO_ANDRE_WFS,
)


class FakeJundiaiGeocoder:
    def geocode(self, _query):
        return {"latitude": -23.1857, "longitude": -46.8967}


def polygon():
    return {
        "type": "Polygon",
        "coordinates": [[
            [-46.8968, -23.1858], [-46.8966, -23.1858],
            [-46.8966, -23.1856], [-46.8968, -23.1858],
        ]],
    }


def test_jundiai_public_wfs_map_candidates_have_no_fiscal_inscription(tmp_path):
    paths = []
    def handler(request):
        paths.append(request.url.path)
        q = dict(request.url.params)
        assert q["service"] == "WFS"
        assert q["typeName"] == JUNDIAI_LAYER
        assert q["maxFeatures"] == "20"
        assert "EPSG:4326" in q["bbox"]
        return httpx.Response(200, json={"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"gid": 42, "lotes_jund": "R12"},
             "geometry": polygon()},
        ]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(
        cache_dir=tmp_path, client=client, geocoder=FakeJundiaiGeocoder()
    )
    records = adapter.search(SearchRequest(
        address="Avenida Nove de Julho", number="100", city="Jundiaí", state="SP",
    ))
    client.close()
    assert len(paths) == 1
    assert len(records) == 1
    record = records[0]
    assert record.block is None and record.lot is None
    assert record.attributes["sql"] is None
    assert record.attributes["iptu_registration_number"] is None
    assert record.attributes["municipal_registration_number"] is None
    assert record.attributes["cadastre_match"] == "spatial_candidate_only"
    assert record.attributes["map_feature_id"] == "42"
    assert record.provenance[0].confidence == 0.2
    assert json.loads(record.attributes["geometry_geojson"])["type"] == "Polygon"
    assert adapter.last_diagnostics["Jundiaí"]["registration_count"] == 0


def test_jundiai_never_returns_sql_when_wfs_schema_has_only_gid(tmp_path):
    def handler(_request):
        return httpx.Response(200, json={"features": [{
            "properties": {"gid": 1, "lotes_jund": 1, "iptu": "FORGED"},
            "geometry": polygon(),
        }]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(
        cache_dir=tmp_path, client=client, geocoder=FakeJundiaiGeocoder()
    )
    rows = adapter.search(SearchRequest(
        address="Avenida Nove de Julho", number="100", city="Jundiaí", state="SP",
    ))
    client.close()
    assert len(rows) == 1
    assert rows[0].attributes["sql"] is None
    assert rows[0].attributes["iptu_registration_number"] is None


def test_santo_andre_public_wfs_capabilities_are_not_sql_address_join(tmp_path):
    xml = """<?xml version="1.0"?>
      <wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs">
        <wfs:FeatureTypeList>
          <wfs:FeatureType><wfs:Name>siga:SIGA_LIM_BAIRROS</wfs:Name></wfs:FeatureType>
        </wfs:FeatureTypeList>
      </wfs:WFS_Capabilities>"""
    def handler(request):
        assert request.url.path == "/geoserver/ows"
        assert request.url.params["request"] == "GetCapabilities"
        return httpx.Response(200, text=xml)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    result = adapter.search(SearchRequest(
        address="Rua das Figueiras", number="100",
        city="Santo André", state="SP",
    ))
    client.close()
    assert result == []
    diag = adapter.last_diagnostics["Santo André"]
    assert diag["result"] == "no_public_fiscal_address_layer_in_wfs"
    assert diag["registration_verified"] is False
    assert diag["official_portal_url"] == SANTO_ANDRE_PORTAL
    assert "Santo André" not in adapter.last_errors


def test_santo_andre_malformed_wfs_is_not_silent_no_property(tmp_path):
    def handler(_request):
        return httpx.Response(200, text="not XML")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    assert adapter.search(SearchRequest(
        address="Rua das Figueiras", number="100",
        city="Santo André", state="SP",
    )) == []
    client.close()
    assert "Santo André" in adapter.last_errors


def test_sp_candidates_require_numeric_address_and_do_not_query(tmp_path):
    def handler(_request):
        raise AssertionError("Unbounded cadastral source request")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    for city in ("Santo André", "Jundiaí"):
        for number in (None, "", "100 OR 1=1"):
            assert adapter.search(SearchRequest(
                address="Rua das Figueiras", number=number,
                city=city, state="SP",
            )) == []
    client.close()


def test_sp_official_endpoints_and_portals_are_https():
    assert JUNDIAI_WFS.startswith("https://geo.jundiai.sp.gov.br/")
    assert JUNDIAI_PORTAL.startswith("https://geo.jundiai.sp.gov.br/")
    assert SANTO_ANDRE_WFS.startswith("https://sigamapa.santoandre.sp.gov.br/")
    assert SANTO_ANDRE_PORTAL.startswith("https://sigamapa.santoandre.sp.gov.br/")
