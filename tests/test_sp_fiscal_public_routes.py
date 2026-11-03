"""Public source discovery never makes private tax record requests."""
import importlib.util
from pathlib import Path

import httpx

path = Path(__file__).resolve().parents[1] / "scripts" / "probe_sp_fiscal_public_routes.py"
spec = importlib.util.spec_from_file_location("fiscal_routes", path)
assert spec is not None and spec.loader is not None
fiscal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fiscal)


def test_route_parser_discards_dynamic_query_and_sensitive_routes():
    result = fiscal.public_route_names(
        'url: "/public/map/query?id=12345",\n'
        'url: "/private/login?token=SECRET",\n'
        'url: "/geoserver/wfs?token=123",\n'
        'url: "/service/getCadastre.jsp",\n'
    )
    assert all("SECRET" not in path and "?" not in path for path in result)
    assert "/service/getCadastre.jsp" in result


def test_official_scripts_do_not_fetch_external_js_or_url_params():
    urls = fiscal._official_scripts(
        "https://sigamapa.santoandre.sp.gov.br/index.aspx?id=search_sql",
        [
            "/js/app.js", "/js/mapa-fiscal.js",
            "https://other.example/js/hijack.js",
            "javascript:alert(1)",
        ],
    )
    assert len(urls) == 2
    assert all(url.startswith("https://sigamapa.santoandre.sp.gov.br/") for url in urls)


def test_public_portal_metadata_only_no_login_requests():
    seen = []
    def handler(request):
        seen.append((request.method, request.url.path))
        assert request.method == "GET"
        if request.url.path.endswith("/index.aspx"):
            return httpx.Response(
                200, text='<script src="/js/app.js"></script>'
                '<script>const p="/map/fiscal.jsp";</script>',
            )
        assert request.url.path == "/js/app.js"
        return httpx.Response(200, text='const api="/api/map/query";')
    portal = "https://sigamapa.santoandre.sp.gov.br/index.aspx?id=search_sql"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fiscal.probe(client, "Santo André", portal)
    assert result["result"] == "public_html_accessible"
    assert len(seen) == 2
    assert all("login" not in p for _, p in seen)
    assert result["scripts"][0]["public_route_names"] == ["/api/map/query"]


def test_offline_portal_is_diagnostic_not_empty_property():
    def handler(_request):
        raise httpx.ConnectTimeout("municipality unavailable")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fiscal.probe(
            client, "Campinas", "https://zoneamento.campinas.sp.gov.br/"
        )
    assert result["result"] == "source_unavailable"
    assert result["error_type"] == "ConnectTimeout"
