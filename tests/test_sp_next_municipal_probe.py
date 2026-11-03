"""Public GIS discovery must not turn network errors into cadastral claims."""
import importlib.util
from pathlib import Path

import httpx

# Script is a standalone QA utility, not an installed Python package.
probe_path = Path(__file__).resolve().parents[1] / "scripts" / "probe_sp_next_municipal.py"
spec = importlib.util.spec_from_file_location("sp_next_probe", probe_path)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

RIBEIRAO_PORTAL_SEARCH = probe.RIBEIRAO_PORTAL_SEARCH
RIBEIRAO_REST = probe.RIBEIRAO_REST
SJC_PUBLIC_PORTAL = probe.SJC_PUBLIC_PORTAL
SJC_WFS_CANDIDATES = probe.SJC_WFS_CANDIDATES
list_arcgis = probe.list_arcgis
list_geosanja = probe.list_geosanja


def test_ribeirao_public_catalogue_inspects_metadata_only():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        assert request.method == "GET"
        assert request.url.params["f"] == "json"
        if request.url.path.endswith("/server/rest/services"):
            return httpx.Response(200, json={
                "folders": ["Hosted", "System"], "services": [
                    {"name": "Cadastro_Urbano", "type": "MapServer"},
                ],
            })
        if request.url.path.endswith("/server/rest/services/Hosted"):
            return httpx.Response(200, json={
                "services": [{"name": "Hosted/Divisao_Lotes", "type": "FeatureServer"}],
            })
        assert request.url.path.endswith("/portal/sharing/rest/search")
        return httpx.Response(200, json={
            "total": 1, "results": [
                {"title": "Lotes públicos", "type": "Feature Service",
                 "access": "public", "id": "public-service-1",
                 "url": "https://webgis.ribeiraopreto.sp.gov.br/server/rest/services"},
            ],
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    results = list_arcgis(client)
    client.close()
    assert len(requested) == 3
    assert results[0]["service_count"] == 1
    assert results[1]["folder"] == "Hosted"
    assert results[2]["items"][0]["access"] == "public"
    assert RIBEIRAO_REST in requested[0]
    assert RIBEIRAO_PORTAL_SEARCH in requested[-1]
    assert all("/query" not in url for url in requested)


def test_ribeirao_connection_failure_is_reported_without_fabricating_cadastre():
    def handler(_request):
        raise httpx.ConnectError("municipal source unavailable")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    results = list_arcgis(client)
    client.close()
    assert len(results) == 2
    assert all(item["error_type"] == "ConnectError" for item in results)
    assert all("inscription" not in item for item in results)


def test_geosanja_nonpublic_wfs_paths_do_not_become_fiscal_sources():
    called = []

    def handler(request):
        called.append(str(request.url))
        if request.url.path == "/":
            return httpx.Response(200, text="<html><head><title>GEO</title></head></html>")
        return httpx.Response(404, text="WFS not found")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = list_geosanja(client)
    client.close()
    assert len(called) == 1 + len(SJC_WFS_CANDIDATES)
    assert called[0] == SJC_PUBLIC_PORTAL
    assert result[0]["http_status"] == 200
    assert result[0]["script_paths"] == []
    assert all(row.get("error_type") == "HTTPStatusError" for row in result[1:])
    assert all("/query" not in url and "token" not in url for url in called)


def test_geosanja_valid_public_wfs_metadata_does_not_read_property_records():
    xml = """<?xml version="1.0"?>
      <wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs">
        <wfs:FeatureTypeList>
          <wfs:FeatureType>
            <wfs:Name>geosanja:lotes_publicos</wfs:Name>
            <wfs:Title>Polígonos de lotes</wfs:Title>
          </wfs:FeatureType>
        </wfs:FeatureTypeList>
      </wfs:WFS_Capabilities>"""
    requested = []

    def handler(request):
        requested.append(str(request.url))
        if request.url.path == "/":
            return httpx.Response(200, text="<html></html>")
        if request.url.path == "/geoserver/ows":
            return httpx.Response(200, text=xml)
        return httpx.Response(404, text="not published")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = list_geosanja(client)
    client.close()
    published = [item for item in result if item.get("candidate_count") == 1]
    assert len(published) == 1
    assert published[0]["candidate_types"][0]["name"] == "geosanja:lotes_publicos"
    assert all("GetFeature" not in url and "/query" not in url for url in requested)
