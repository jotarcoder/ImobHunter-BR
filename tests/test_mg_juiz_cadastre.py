"""Juiz de Fora official INSCID + loteid linkage tests."""
import json

import httpx

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.official_municipal_services import OfficialMunicipalServicesAdapter
from imobhunter.sources.mg_juiz_cadastre import JUIZ_INSCRIPTIONS, JUIZ_PARCELS


def polygon():
    return {"rings": [[
        [-43.351, -21.763], [-43.350, -21.763],
        [-43.350, -21.762], [-43.351, -21.763],
    ]]}


def test_juiz_exact_address_inscription_joined_to_block_and_lot(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        params = dict(request.url.params)
        if "/inscricoes_imobiliarias_geocentro/" in request.url.path:
            assert "BRASIL" in params["where"]
            assert "'2001'" in params["where"]
            assert params["returnGeometry"] == "false"
            return httpx.Response(200, json={"features": [
                {"attributes": {
                    "OBJECTID": 6, "INSCID": "JF-239842",
                    "Logradouro": "AVENIDA BRASIL", "Numero": "2001",
                    "loteid": 123.0, "Area_Lote": 300.5,
                }},
                {"attributes": {
                    "OBJECTID": 7, "INSCID": "WRONG",
                    "Logradouro": "RUA OUTRA", "Numero": "2001",
                    "loteid": 124,
                }},
            ]})
        assert request.url.path.endswith("/Cadastro_Recadastramento_2026_08_10/MapServer/0/query")
        assert params["where"] == "loteid IN (123)"
        return httpx.Response(200, json={"features": [
            {"attributes": {"loteid": 123, "quadra": "059", "numero_lot": "0212"},
             "geometry": polygon()},
        ]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    records = adapter.search(SearchRequest(
        address="Avenida Brasil", number="2001", city="Juiz de Fora", state="MG",
    ))
    client.close()
    assert len(calls) == 2
    assert len(records) == 1
    assert records[0].block == "059"
    assert records[0].lot == "0212"
    assert records[0].area_m2 == 300.5
    assert records[0].attributes["iptu_registration_number"] == "JF-239842"
    assert records[0].attributes["municipal_registration_number"] == "JF-239842"
    assert records[0].attributes["sql"] is None
    assert records[0].attributes["parcel_identifier"] == "123"
    assert records[0].attributes["cadastre_match"] == "exact_address_match"
    assert json.loads(records[0].attributes["geometry_geojson"])["type"] == "Polygon"


def test_juiz_no_polygon_never_infers_quadra_or_lot(tmp_path):
    def handler(request):
        if "/inscricoes_imobiliarias_geocentro/" in request.url.path:
            return httpx.Response(200, json={"features": [{
                "attributes": {
                    "INSCID": "J.F. 123", "Logradouro": "AVENIDA BRASIL",
                    "Numero": "2001", "loteid": 123,
                },
            }]})
        return httpx.Response(200, json={"features": []})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    records = adapter.search(SearchRequest(
        address="Avenida Brasil", number="2001", city="Juiz de Fora", state="MG",
    ))
    client.close()
    assert len(records) == 1
    assert records[0].block is None and records[0].lot is None
    assert records[0].attributes["iptu_registration_number"] == "J.F. 123"
    assert records[0].attributes["parcel_join_status"] == "parcel_not_returned"


def test_juiz_ambiguous_polygon_does_not_assign_first(tmp_path):
    def handler(request):
        if "/inscricoes_imobiliarias_geocentro/" in request.url.path:
            return httpx.Response(200, json={"features": [{
                "attributes": {
                    "INSCID": "REAL-123", "Logradouro": "AVENIDA BRASIL",
                    "Numero": "2001", "loteid": 123,
                },
            }]})
        return httpx.Response(200, json={"features": [
            {"attributes": {"loteid": 123, "quadra": "111", "numero_lot": "001"},
             "geometry": polygon()},
            {"attributes": {"loteid": 123, "quadra": "222", "numero_lot": "002"},
             "geometry": polygon()},
        ]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    records = adapter.search(SearchRequest(
        address="Avenida Brasil", number="2001", city="Juiz de Fora", state="MG",
    ))
    client.close()
    assert len(records) == 1
    assert records[0].block is None
    assert records[0].lot is None
    assert records[0].attributes["parcel_join_status"] == "ambiguous_loteid"


def test_juiz_missing_number_and_sql_injection_rejected_without_calls(tmp_path):
    def handler(_request):
        raise AssertionError("Should never make an unbounded request")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    for number in (None, "", "0 OR 1=1", "abc"):
        assert adapter.search(SearchRequest(
            address="Avenida Brasil", number=number, city="Juiz de Fora", state="MG",
        )) == []
    client.close()


def test_juiz_wrong_state_never_reaches_juiz_endpoint(tmp_path):
    def handler(_request):
        raise AssertionError("Cannot send RJ requests to Juiz de Fora")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    assert adapter.search(SearchRequest(
        address="Avenida Brasil", number="2001", city="Juiz de Fora", state="RJ",
    )) == []
    client.close()


def test_juiz_endpoints_are_official_https():
    assert JUIZ_INSCRIPTIONS.startswith("https://sisurb.pjf.mg.gov.br/")
    assert JUIZ_PARCELS.startswith("https://sisurb.pjf.mg.gov.br/")
