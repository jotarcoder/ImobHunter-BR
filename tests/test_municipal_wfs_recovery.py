"""Regression checks for municipal WFS failures without pretending an empty cadastre.

No network is used: the handlers reproduce actual WFS response classes and
verify bounded retries, layer isolation, and errors visible to the user.
"""
from __future__ import annotations

import httpx

from imobhunter.application.search import SearchService
from imobhunter.domain.models import SearchRequest
from imobhunter.sources.official_municipal_services import OfficialMunicipalServicesAdapter

CAPABILITIES = """<?xml version="1.0"?>
<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0">
  <wfs:FeatureTypeList>
    <wfs:FeatureType>
      <wfs:Name>fiscal:lotes_sql</wfs:Name>
      <wfs:Title>Lotes SQL</wfs:Title>
    </wfs:FeatureType>
    <wfs:FeatureType>
      <wfs:Name>cadastro:lotes</wfs:Name>
      <wfs:Title>Lotes cadastrais</wfs:Title>
    </wfs:FeatureType>
  </wfs:FeatureTypeList>
</wfs:WFS_Capabilities>"""


class Geocoder:
    def geocode(self, _address):
        return {"latitude": -23.934, "longitude": -46.326}


def _request():
    return SearchRequest(
        address="Praça Visconde de Mauá", city="Santos", state="SP"
    )


def _adapter(tmp_path, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OfficialMunicipalServicesAdapter(
        cache_dir=tmp_path / "cache", geocoder=Geocoder(), client=client,
    ), client


def test_santos_wfs_fails_first_layer_then_keeps_the_second_official_lot(tmp_path):
    observed = []

    def handler(req):
        q = dict(req.url.params)
        if q.get("request") == "GetCapabilities":
            return httpx.Response(200, text=CAPABILITIES)
        observed.append(q)
        if q.get("typeNames") == "fiscal:lotes_sql" or q.get("typeName") == "fiscal:lotes_sql":
            return httpx.Response(400, text="<ServiceException>Unsupported feature type</ServiceException>")
        assert q.get("typeNames") == "cadastro:lotes"
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [{
                "id": "cadastro.42", "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[
                    [-46.327, -23.935], [-46.326, -23.935],
                    [-46.326, -23.934], [-46.327, -23.935],
                ]]},
                "properties": {"quadra": "010", "lote": "042", "area_terreno": 180},
            }],
        })

    adapter, client = _adapter(tmp_path, handler)
    try:
        records = adapter.search(_request())
    finally:
        client.close()
    assert len(records) == 1
    assert records[0].block == "010"
    assert records[0].lot == "042"
    assert records[0].area_m2 == 180
    assert records[0].attributes["geometry_geojson"]
    assert records[0].attributes["iptu_registration_number"] is None
    assert "Santos" not in adapter.last_errors
    assert [q["version"] for q in observed] == ["2.0.0", "1.1.0", "1.0.0", "2.0.0"]
    assert observed[0]["typeNames"] == "fiscal:lotes_sql"
    assert observed[0]["count"] == "40"
    assert "startIndex" not in observed[1]
    assert observed[1]["typeName"] == "fiscal:lotes_sql"
    assert observed[1]["maxFeatures"] == "40"
    assert adapter.last_diagnostics["Santos"]["queries"][0]["error"] == "http_400"
    assert adapter.last_diagnostics["Santos"]["result"] == "records_returned"


def test_all_wfs_layers_rejected_reports_error_not_no_cadastral_match(tmp_path):
    def handler(req):
        if req.url.params.get("request") == "GetCapabilities":
            return httpx.Response(200, text=CAPABILITIES)
        return httpx.Response(400, text="<ServiceException>Query rejected</ServiceException>")

    adapter, client = _adapter(tmp_path, handler)
    try:
        records = adapter.search(_request())
        status, returned = SearchService._search_source(adapter, _request())
    finally:
        client.close()
    assert records == []
    assert "Santos" in adapter.last_errors
    assert adapter.last_diagnostics["Santos"]["result"] == "all_cadastral_layers_failed"
    assert status.status == "error"
    assert status.records_count == 0
    assert "Falha na fonte municipal" in (status.message or "")
    assert returned == []


def test_successful_empty_wfs_is_not_treated_as_http_failure(tmp_path):
    def handler(req):
        if req.url.params.get("request") == "GetCapabilities":
            return httpx.Response(200, text=CAPABILITIES)
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

    adapter, client = _adapter(tmp_path, handler)
    try:
        status, records = SearchService._search_source(adapter, _request())
    finally:
        client.close()
    assert status.status == "no_results"
    assert records == []
    assert not adapter.last_errors
    assert adapter.last_diagnostics["Santos"]["result"] == "no_features_in_bbox"


def test_server_outage_has_no_retries_or_insecure_tls_fallback(tmp_path):
    requested_versions = []

    def handler(req):
        if req.url.params.get("request") == "GetCapabilities":
            return httpx.Response(200, text=CAPABILITIES)
        requested_versions.append(req.url.params.get("version"))
        return httpx.Response(503, text="temporarily unavailable")

    adapter, client = _adapter(tmp_path, handler)
    try:
        status, records = SearchService._search_source(adapter, _request())
    finally:
        client.close()
    assert status.status == "error"
    assert records == []
    assert requested_versions == ["2.0.0"]
    assert adapter.last_diagnostics["Santos"]["queries"][0]["error"] == "http_503"


def test_tls_failure_is_not_described_as_missing_lot(tmp_path):
    def handler(_req):
        raise httpx.ConnectError("CERTIFICATE_VERIFY_FAILED")

    adapter, client = _adapter(tmp_path, handler)
    try:
        status, records = SearchService._search_source(adapter, _request())
    finally:
        client.close()
    assert status.status == "error"
    assert not records
    assert "CERTIFICATE_VERIFY_FAILED" in (status.message or "")



def test_empty_secondary_layer_cannot_hide_failed_primary_cadastre(tmp_path):
    """A responding geometry-only layer does not prove missing SQL records."""
    def handler(req):
        q = dict(req.url.params)
        if q.get("request") == "GetCapabilities":
            return httpx.Response(200, text=CAPABILITIES)
        layer = q.get("typeNames") or q.get("typeName")
        if layer == "fiscal:lotes_sql":
            return httpx.Response(400, text="Unsupported cadastral layer")
        return httpx.Response(
            200, json={"type": "FeatureCollection", "features": []}
        )

    adapter, client = _adapter(tmp_path, handler)
    try:
        status, records = SearchService._search_source(adapter, _request())
    finally:
        client.close()
    assert not records
    assert status.status == "error"
    assert adapter.last_diagnostics["Santos"]["result"] == (
        "partial_layer_failure_no_records"
    )


def test_bertioga_unavailable_tls_remains_external_error(tmp_path):
    """Do not mistake the user's reported offline endpoint for no lot."""
    class BertiogaGeocoder:
        def geocode(self, _query):
            return {"latitude": -23.850, "longitude": -46.140}

    def handler(_request):
        raise httpx.ConnectError("CERTIFICATE_VERIFY_FAILED")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(
        cache_dir=tmp_path / "cache2", geocoder=BertiogaGeocoder(), client=client
    )
    try:
        status, records = SearchService._search_source(
            adapter, SearchRequest(
                address="Avenida Anchieta", number="1000",
                city="Bertioga", state="SP",
            )
        )
    finally:
        client.close()
    assert status.status == "error"
    assert not records
    assert "CERTIFICATE_VERIFY_FAILED" in (status.message or "")
    assert "Bertioga" in adapter.last_errors
