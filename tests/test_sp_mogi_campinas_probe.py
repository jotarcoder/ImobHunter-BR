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


def test_cadastral_resource_probe_reads_only_bounded_csv_column_header():
    requests = []
    def handler(request):
        requests.append((request.url.path, dict(request.headers)))
        if request.url.path.endswith("/package_show"):
            assert request.url.params["id"] in (
                "cadastro-imobiliario", "lista-de-logradouros-visao-financas"
            )
            return httpx.Response(200, json={"success": True, "result": {
                "title": "CADASTRO IMOBILIÁRIO", "license_id": "cc-by",
                "metadata_modified": "2026-10-30",
                "resources": [
                    {"name": "2026", "format": "CSV", "size": 9000,
                     "url": "https://dados.mogidascruzes.sp.gov.br/dataset/cadastro.csv"},
                    {"name": "untrusted", "format": "CSV",
                     "url": "https://other.example.org/untrusted.csv"},
                ],
            }})
        assert request.url.path == "/dataset/cadastro.csv"
        assert request.headers["range"] == "bytes=0-4095"
        return httpx.Response(206, content=(
            b"LOGRADOURO;NUMERO;SETOR;QUADRA;LOTE;INSCRICAO\n"
            b"Rua Teste;100;01;02;003;123\n"
        ))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        records = probe.probe_mogi_cadastre_metadata(client)
    assert len(records) == 2
    assert len(requests) == 4
    assert records[0]["csv_public_schemas"][0]["column_count"] == 6
    assert "INSCRICAO" in records[0]["csv_public_schemas"][0]["column_names_only"]
    assert "Rua Teste" not in str(records)


def test_ckan_header_probe_never_follows_untrusted_redirect():
    def handler(request):
        assert request.headers["range"] == "bytes=0-4095"
        return httpx.Response(302, headers={"location": "https://private.example/collect"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        data = probe._csv_header_only(
            client, "https://dados.mogidascruzes.sp.gov.br/files/2026.csv"
        )
    assert data["status"] == "redirect_not_followed"
    assert probe._official_resource_url("https://evil.example/files.csv") is False
