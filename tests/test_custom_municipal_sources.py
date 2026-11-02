"""Municipal additions: per-city routing, persistence, file imports and honest APIs."""
from __future__ import annotations

import json

import httpx
import pytest

from imobhunter.application.custom_municipal_sources import (
    CustomMunicipalStore, infer_protocol, read_municipal_file, safe_public_url,
)
from imobhunter.application.search import SearchService
from imobhunter.application.source_probe import probe_endpoint
from imobhunter.domain.models import PropertyRecord, SearchRequest
from imobhunter.infrastructure.local_db import LocalDatabase
from imobhunter.sources.custom_municipal import (
    CustomMunicipalAdapter, reload_custom_sources, _AuthorizedRemote,
)
from imobhunter.sources.registry import SourceRegistry


def _store(tmp_path):
    return CustomMunicipalStore(tmp_path / "per_user_sources")


def test_add_persists_reloads_and_removes_without_touching_original(tmp_path):
    store = _store(tmp_path)
    entry = store.add(
        "Geoportal de Santos", "Santos", "sp",
        "https://geo.santos.sp.gov.br/geoserver/ows", "wfs",
    )
    assert entry.state == "SP"
    assert entry.source_id.startswith("local_municipal_")
    assert store.list() == CustomMunicipalStore(store.directory).list()
    original = tmp_path / "municipal.csv"
    original.write_text(
        "logradouro;numero;quadra;lote;sql;area_m2;municipio;uf\n"
        "Rua da Praia;100;001;003;010.020.0030;125,5;Santos;SP\n",
        encoding="utf-8",
    )
    updated, count = store.import_file(entry.source_id, original)
    assert count == 1
    copied = store.local_path(updated)
    assert copied and copied.read_bytes() == original.read_bytes()
    assert copied != original
    assert store.remove(entry.source_id)
    assert not copied.exists()
    assert original.is_file()
    assert not store.list()


def test_csv_local_records_use_exact_city_state_door_number_and_sql(tmp_path):
    store = _store(tmp_path)
    entry = store.add("Cadastro de lotes", "Santos", "SP")
    path = tmp_path / "cadastro.csv"
    path.write_text(
        "logradouro;numero;quadra;lote;sql;area_terreno;municipio;uf\n"
        "Rua São João;100;020;0003;111.020.003;210,5;Santos;SP\n"
        "Rua São João;102;020;0004;111.020.004;180;Santos;SP\n"
        "Rua São João;100;999;0001;999;199;São Paulo;SP\n",
        encoding="utf-8",
    )
    entry, count = store.import_file(entry.source_id, path)
    assert count == 3
    adapter = CustomMunicipalAdapter(entry, store)
    result = adapter.search(SearchRequest(
        address="Rua São João", number="100", city="SANTOS", state="sp",
    ))
    assert len(result) == 1
    assert result[0].block == "020" and result[0].lot == "0003"
    assert result[0].area_m2 == 210.5
    assert result[0].attributes["iptu_registration_number"] == "111.020.003"
    assert result[0].provenance[0].source_id == entry.source_id
    assert adapter.search(SearchRequest(
        address="Rua São João", number="100", city="São Paulo", state="SP",
    )) == []
    assert adapter.search(SearchRequest(
        block="020", lot="4", city="Santos", state="SP",
    ))[0].lot == "0004"
    assert adapter.search(SearchRequest(
        address="Rua São João", number="105", city="Santos", state="SP",
    )) == []


def test_geojson_file_preserves_valid_official_geometry_and_no_invented_sql(tmp_path):
    store = _store(tmp_path)
    entry = store.add("Lotes municipais", "Praia Grande", "SP")
    polygon = {"type": "Polygon", "coordinates": [[
        [-46.42, -24.01], [-46.41, -24.01],
        [-46.41, -24.00], [-46.42, -24.01],
    ]]}
    path = tmp_path / "lotes.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection", "features": [
            {"type": "Feature", "id": "wfs.1", "properties": {
                "quadra": "012", "lote": "002", "area": 145,
            }, "geometry": polygon},
            {"type": "Feature", "id": "wfs.2", "properties": {
                "quadra": "012", "lote": "003", "area": 160,
            }, "geometry": {"type": "Point", "coordinates": [500000, 7400000]}},
        ],
    }), encoding="utf-8")
    entry, count = store.import_file(entry.source_id, path)
    assert count == 2
    a = CustomMunicipalAdapter(entry, store)
    first = a.search(SearchRequest(
        block="12", lot="2", city="Praia Grande", state="SP",
    ))[0]
    assert json.loads(first.attributes["geometry_geojson"]) == polygon
    assert first.attributes["sql"] is None
    assert first.latitude is not None and first.longitude is not None
    second = a.search(SearchRequest(
        block="012", lot="003", city="Praia Grande", state="SP",
    ))[0]
    assert second.attributes["geometry_geojson"] is None
    assert second.latitude is None and second.longitude is None


def test_restarts_add_to_registry_and_only_query_the_matching_municipality(tmp_path):
    store = _store(tmp_path)
    source = store.add("Dados locais", "Bertioga", "SP")
    file = tmp_path / "iptu.json"
    file.write_text(json.dumps({"data": [{
        "endereco": "Avenida Anchieta", "numero": "100",
        "quadra": "01", "lote": "09", "sql": "01.09",
    }]}), encoding="utf-8")
    store.import_file(source.source_id, file)
    registry = SourceRegistry({})
    reload_custom_sources(registry, CustomMunicipalStore(store.directory))
    assert registry.get(source.source_id) is not None
    service = SearchService(registry, LocalDatabase(tmp_path / "search.db"))
    in_city = service.search(SearchRequest(
        address="Avenida Anchieta", number="100", city="Bertioga", state="SP",
    ))
    assert len(in_city.records) == 1
    assert in_city.records[0].attributes["sql"] == "01.09"
    outside = service.search(SearchRequest(
        address="Avenida Anchieta", number="100", city="Santos", state="SP",
    ))
    assert not outside.records and not outside.sources
    reload_custom_sources(registry, store)
    assert len(registry.all()) == 1  # Refresh is idempotent.


def test_website_bookmark_can_be_probed_but_is_not_a_property_api(tmp_path):
    store = _store(tmp_path)
    source = store.add("Prefeitura", "Guarujá", "SP", "https://guaruja.sp.gov.br")
    assert source.kind == "website"
    assert CustomMunicipalAdapter(source, store).status().status == "not_configured"
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text="<html>Portal da cidade</html>")
    )) as client:
        result = probe_endpoint({
            "id": source.source_id, "url": source.url,
            "kind": source.kind, "custom": "true",
        }, client)
    assert result.state == "responded"
    assert "não foi verificada API" in result.message


@pytest.mark.parametrize("url", [
    "http://prefeitura.gov.br/wfs", "https://127.0.0.1/api",
    "https://localhost/geoserver", "https://10.0.0.10/",
    "https://user:pass@prefeitura.sp.gov.br/", "https://service.internal/geoserver",
    "https://prefeitura.gov.br:8080/geoserver", "https://host.local/",
    "file:///etc/passwd", "https://example.com/#x",
])
def test_reject_unsafe_external_endpoints(url):
    assert not safe_public_url(url)


def test_infer_supported_protocol_and_reject_non_layer_arcgis(tmp_path):
    assert infer_protocol("https://exemplo.gov.br/geoserver/ows") == "wfs"
    assert infer_protocol("https://exemplo.gov.br/arcgis/rest/services/CTM/FeatureServer/0") == "arcgis"
    assert infer_protocol("https://exemplo.gov.br/portal") == "website"
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="ArcGIS"):
        store.add("ArcGIS", "Santos", "SP", "https://exemplo.gov.br/portal", "arcgis")
    with pytest.raises(ValueError, match="HTTPS"):
        store.add("Rede interna", "Santos", "SP", "http://127.0.0.1", "wfs")


def test_wfs_remote_is_scoped_and_reuses_existing_municipal_parser(tmp_path):
    store = _store(tmp_path)
    definition = store.add(
        "WFS local", "Santos", "SP", "https://geo.santos.sp.gov.br/ows", "wfs",
    )

    class FakeRemote:
        def __init__(self):
            self.calls = []
        def _geocode(self, request):
            self.calls.append(("geocode", request.city))
            return -23.9, -46.3
        def _wfs_records(self, *args):
            self.calls.append(("wfs", args[0], args[1], args[2]))
            return [PropertyRecord(
                block="001", lot="002", city="Santos", state="SP",
                attributes={"geometry_geojson": None},
            )]
    fake = FakeRemote()
    source = CustomMunicipalAdapter(definition, store, remote=fake)
    req = SearchRequest(address="Rua Exemplo", city="Santos", state="SP")
    records = source.search(req)
    assert len(records) == 1
    assert fake.calls == [
        ("geocode", "Santos"),
        ("wfs", "Santos", "SP", definition.url),
    ]
    assert records[0].provenance[0].source_id == definition.source_id
    assert not source.search(SearchRequest(address="Rua Exemplo", city="Bertioga", state="SP"))
    assert len(fake.calls) == 2


def test_wfs_tls_and_redirect_are_not_ignored():
    remote = _AuthorizedRemote(client=httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"Location": "http://127.0.0.1/"})
    )))
    try:
        with pytest.raises(ValueError, match="Redirecionamento bloqueado"):
            remote._get("https://geo.example.gov.br/ows", {"service": "WFS"})
    finally:
        remote._client.close()


def test_local_excel_import_uses_readonly_rows(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    file = tmp_path / "lots.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(("logradouro", "numero", "quadra", "lote"))
    sheet.append(("Rua do Porto", 10, "001", "02"))
    book.save(file)
    store = _store(tmp_path)
    definition = store.add("Planilha", "Santos", "SP")
    definition, count = store.import_file(definition.source_id, file)
    assert count == 1
    records = CustomMunicipalAdapter(definition, store).search(SearchRequest(
        address="Rua do Porto", number="10", city="Santos", state="SP",
    ))
    assert len(records) == 1 and records[0].lot == "02"


def test_reject_nonmunicipal_formats_and_empty_files(tmp_path):
    store = _store(tmp_path)
    source = store.add("Teste", "Santos", "SP")
    invalid = tmp_path / "test.zip"
    invalid.write_bytes(b"PK\x03\x04")
    with pytest.raises(ValueError):
        store.import_file(source.source_id, invalid)
    empty = tmp_path / "empty.csv"
    empty.write_text("municipio;quadra;lote\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_municipal_file(empty)
    assert store.get(source.source_id).file_name == ""
