"""Municipal SC address-to-parcel tests use official fields, no live mocks of success claims."""
import json

import httpx

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.official_municipal_services import OfficialMunicipalServicesAdapter
from imobhunter.sources.sc_municipal_cadastre import JOINVILLE_LAYER, SAO_BENTO_SERVICE


def polygon():
    return {"rings": [[[-48.85, -26.30], [-48.849, -26.30], [-48.849, -26.299], [-48.85, -26.30]]]}


def test_joinville_qualified_fields_exact_address_and_inscription(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path.endswith("/lotes_joinsgc_sefaz/MapServer/0/query")
        params = dict(request.url.params)
        assert params["outSR"] == "4326"
        assert "2550" in params["where"]
        assert "CONDEIXA" in params["where"]
        return httpx.Response(200, json={"features": [
            {"attributes": {
                "gisdb.gisadmin.mvw_lote.logradouro": "ALUISIO PIRES CONDEIXA",
                "gisdb.gisadmin.mvw_lote.numero": 2550,
                "gisdb.gisadmin.lotes.iq": "13-20-12-16-1356",
                "gisdb.gisadmin.lotes.quadra": "16",
                "gisdb.gisadmin.lotes.lote": 1356,
                "gisdb.gisadmin.mvw_lote.area_terreno": 580.4,
                "gisdb.gisadmin.lotes.objectid": 10,
            }, "geometry": polygon()},
            {"attributes": {
                "gisdb.gisadmin.mvw_lote.logradouro": "RUA DIFERENTE",
                "gisdb.gisadmin.mvw_lote.numero": 2550,
                "gisdb.gisadmin.lotes.iq": "WRONG",
            }, "geometry": polygon()},
        ]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(
        cache_dir=tmp_path, client=client,
        geocoder=None,  # Exact address matches do not require geocoding.
    )
    found = adapter.search(SearchRequest(
        address="Avenida Aluísio Pires Condeixa", number="2550",
        city="Joinville", state="SC",
    ))
    client.close()
    assert len(calls) == 1
    assert len(found) == 1
    record = found[0]
    assert record.block == "16"
    assert record.lot == "1356"
    assert record.area_m2 == 580.4
    assert record.attributes["iptu_registration_number"] == "13-20-12-16-1356"
    assert record.attributes["sql"] is None
    assert record.attributes["cadastre_match"] == "exact_address_match"
    assert json.loads(record.attributes["geometry_geojson"])["type"] == "Polygon"
    assert adapter.last_diagnostics["Joinville"]["candidate_count"] == 2


def test_joinville_never_invents_registration_for_unmatched_street(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"features": [{
            "attributes": {
                "gisdb.gisadmin.mvw_lote.logradouro": "RUA OUTRA",
                "gisdb.gisadmin.mvw_lote.numero": 2550,
                "gisdb.gisadmin.lotes.iq": "NOT-THIS-PROPERTY",
            },
            "geometry": polygon(),
        }]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    assert adapter.search(SearchRequest(
        address="Avenida Aluísio Pires Condeixa", number="2550",
        city="Joinville", state="SC",
    )) == []
    client.close()
    assert adapter.last_diagnostics["Joinville"]["result"] == "no_exact_address_match"


def test_sao_bento_exact_address_geolot_join_to_lot_and_terreno_registration(tmp_path):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        params = dict(request.url.params)
        if request.url.path.endswith("/11/query"):
            assert "75" in params["where"] and "LACERDA" in params["where"]
            return httpx.Response(200, json={"features": [
                {"attributes": {
                    "geolot": "SBS-001", "tipo_endereco": 1,
                    "descricao_logradouro": "RUA JORGE LACERDA", "numero": "75",
                    "quadra": "Q12", "lote": "L09",
                }},
                {"attributes": {
                    "geolot": "UNRELATED", "tipo_endereco": 1,
                    "descricao_logradouro": "RUA OUTRA", "numero": "75",
                }},
            ]})
        if request.url.path.endswith("/0/query"):
            assert "'SBS-001'" in params["where"]
            assert "UNRELATED" not in params["where"]
            return httpx.Response(200, json={"features": [{
                "attributes": {"geolot": "SBS-001", "objectid": 25, "area_sig_": 350},
                "geometry": polygon(),
            }]})
        assert request.url.path.endswith("/14/query")
        assert "tipo_cadastro = 1" in params["where"]
        return httpx.Response(200, json={"features": [{
            "attributes": {
                "geolot": "SBS-001", "tipo_cadastro": 1,
                "inscricao_imobiliaria": "SBS-2026-123",
                "area_terreno": 330,
            },
        }]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    records = adapter.search(SearchRequest(
        address="Rua Jorge Lacerda", number="75",
        city="São Bento do Sul", state="SC",
    ))
    client.close()
    assert len(paths) == 3
    assert len(records) == 1
    record = records[0]
    assert record.block == "Q12"
    assert record.lot == "L09"
    assert record.area_m2 == 330
    assert record.attributes["parcel_identifier"] == "SBS-001"
    assert record.attributes["iptu_registration_number"] == "SBS-2026-123"
    assert record.attributes["sql"] is None
    assert record.attributes["cadastre_match"] == "exact_address_match"
    assert json.loads(record.attributes["geometry_geojson"])["type"] == "Polygon"


def test_sao_bento_multiple_registrations_not_assigned_to_wrong_lot(tmp_path):
    def handler(request):
        if request.url.path.endswith("/11/query"):
            return httpx.Response(200, json={"features": [{
                "attributes": {"geolot": "KEY", "descricao_logradouro": "JORGE LACERDA", "numero": "75"},
            }]})
        if request.url.path.endswith("/0/query"):
            return httpx.Response(200, json={"features": [{
                "attributes": {"geolot": "KEY", "quadra": "2", "lote": "3"},
                "geometry": polygon(),
            }]})
        return httpx.Response(200, json={"features": [
            {"attributes": {"geolot": "KEY", "tipo_cadastro": 1, "inscricao_imobiliaria": "ONE"}},
            {"attributes": {"geolot": "KEY", "tipo_cadastro": 1, "inscricao_imobiliaria": "TWO"}},
        ]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    records = adapter.search(SearchRequest(
        address="Rua Jorge Lacerda", number="75", city="São Bento do Sul", state="SC",
    ))
    client.close()
    assert len(records) == 1
    assert records[0].attributes["iptu_registration_number"] is None
    assert records[0].attributes["registration_ambiguity_count"] == 2
    assert records[0].block == "2" and records[0].lot == "3"


def test_sc_municipal_queries_require_number_and_never_run_unbounded(tmp_path):
    def handler(_request):
        raise AssertionError("No HTTP call should be attempted without a number")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    for city in ("Joinville", "São Bento do Sul"):
        assert adapter.search(SearchRequest(address="Rua Jorge Lacerda", city=city, state="SC")) == []
        assert adapter.search(SearchRequest(
            address="Rua Jorge Lacerda", number="1 OR 1=1", city=city, state="SC",
        )) == []
    client.close()


def test_sc_endpoint_is_government_https():
    assert JOINVILLE_LAYER.startswith("https://geo.joinville.sc.gov.br/")
    assert SAO_BENTO_SERVICE.startswith("https://geo.saobentodosul.sc.gov.br/")
