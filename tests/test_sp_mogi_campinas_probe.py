"""Verify that municipal discovery only reads public catalogue metadata."""
import importlib.util
from pathlib import Path

import httpx

path = Path(__file__).resolve().parents[1] / "scripts" / "probe_sp_mogi_campinas.py"
spec = importlib.util.spec_from_file_location("mogi_campinas_probe", path)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_public_html_does_not_fetch_other_hosts():
    paths = []
    def handler(request):
        paths.append(str(request.url))
        if request.url.path == "/mapa":
            return httpx.Response(200, text=(
                '<script src="/static/app.js"></script>'
                '<script src="https://not-municipal.example/injected.js"></script>'
            ))
        assert request.url.host == "geomogi.mogidascruzes.sp.gov.br"
        return httpx.Response(200, text='const service="/geoserver/ows";')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rows = probe.probe_site(client, "Mogi das Cruzes", probe.MOGI_MAP)
    assert len(paths) == 2
    assert all("not-municipal.example" not in p for p in paths)
    assert rows[0]["script_paths"] == ["/static/app.js"]


def test_public_ckan_reads_only_package_metadata():
    seen = []
    def handler(request):
        seen.append(request.url.path)
        assert request.url.params["rows"] == "8"
        return httpx.Response(200, json={"success": True, "result": {
            "count": 1, "results": [{
                "title": "Mapa de quadras", "name": "mapa-quadras",
                "resources": [{"format": "SHP", "url": "https://example.com/private"}],
            }],
        }})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rows = probe.probe_ckan(client)
    assert len(rows) == 5
    assert all("/package_search" in path for path in seen)
    assert rows[0]["datasets"][0]["resource_formats"] == ["SHP"]
    assert "private" not in str(rows)


def test_offline_catalogue_returns_diagnostic_not_empty_property():
    def handler(_request):
        raise httpx.ConnectTimeout("origin timeout")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rows = probe.probe_ckan(client)
        sites = probe.probe_site(client, "Mogi das Cruzes", probe.MOGI_MAP)
    assert all(row["error_type"] == "ConnectTimeout" for row in rows)
    assert sites[0]["error_type"] == "ConnectTimeout"


def test_js_metadata_never_reports_secret_url_parameters():
    result = probe.script_metadata(
        'const u = {url:"/api/lotes/query", layer:"lotes"};\n'
        'const secret = {url:"/api/login?token=SECRET", layer:"lotes"};'
    )
    assert any("/api/" in path for path in result["public_route_hints"])
    assert all("token" not in path for path in result["public_route_hints"])
