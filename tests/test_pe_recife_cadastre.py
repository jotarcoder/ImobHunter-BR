"""Recife ESIG public street/number to polygon, quadra, lote and municipal sequence."""
import json

import httpx

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.official_municipal_services import OfficialMunicipalServicesAdapter
from imobhunter.sources.pe_recife_cadastre import RECIFE_LOTS, RECIFE_LOTS_FEATURE


def polygon():
    return {"rings": [[[-34.883, -8.063], [-34.882, -8.063],
                       [-34.882, -8.062], [-34.883, -8.063]]]}


def search(adapter, address="Avenida Conde da Boa Vista", number="100"):
    return adapter.search(SearchRequest(address=address, number=number,
                                        city="Recife", state="PE"))


def test_recife_exact_address_returns_quadra_lote_sequencial_and_polygon(tmp_path):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        assert request.url.path.endswith("/MapServer/3/query")
        params = dict(request.url.params)
        assert "CONDE" in params["where"] and "100" in params["where"]
        assert params["outSR"] == "4326"
        return httpx.Response(200, json={"features": [
            {"attributes": {
                "OBJECTID": 42, "NMENDCOMP": "AVENIDA CONDE DA BOA VISTA",
                "ENDNUMERO": 100, "QUADRA": 7, "LOTE": 19,
                "AREALOTE": 330.4, "SEQIMOVEL": 123456,
                "DSQFL": "01.04.007.0019", "DISTRITO": 1, "SETOR": 4,
            }, "geometry": polygon()},
            {"attributes": {
                "NMENDCOMP": "RUA OUTRA", "ENDNUMERO": 100,
                "SEQIMOVEL": 55555,
            }, "geometry": polygon()},
        ]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    records = search(adapter)
    client.close()
    assert len(seen) == 1
    assert len(records) == 1
    record = records[0]
    assert record.block == "7"
    assert record.lot == "19"
    assert record.area_m2 == 330.4
    assert record.attributes["iptu_registration_number"] == "123456"
    assert record.attributes["municipal_sequence_number"] == "123456"
    assert record.attributes["sql"] is None
    assert record.attributes["parcel_identifier"] == "01.04.007.0019"
    assert record.attributes["cadastre_match"] == "exact_address_match"
    assert json.loads(record.attributes["geometry_geojson"])["type"] == "Polygon"
    assert adapter.last_diagnostics["Recife"]["registration_count"] == 1


def test_recife_fallback_to_second_documented_official_layer_on_timeout(tmp_path):
    urls = []
    def handler(request):
        urls.append(request.url.path)
        if "/MapServer/3/query" in request.url.path:
            raise httpx.ConnectTimeout("primary ESIG unavailable")
        assert "/FeatureServer/3/query" in request.url.path
        return httpx.Response(200, json={"features": [{
            "attributes": {
                "NMENDCOMP": "AV CONDE DA BOA VISTA", "ENDNUMERO": 100,
                "QUADRA": 3, "LOTE": 4, "SEQIMOVEL": 0,
            },
            "geometry": polygon(),
        }]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    records = search(adapter)
    client.close()
    assert len(urls) == 2 and len(records) == 1
    assert records[0].block == "3" and records[0].lot == "4"
    assert records[0].attributes["iptu_registration_number"] is None
    assert records[0].attributes["service_url"] == RECIFE_LOTS_FEATURE
    assert adapter.last_diagnostics["Recife"]["attempts"][0]["result"] == "ConnectTimeout"


def test_recife_does_not_consider_nearby_parcel_an_address_match(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"features": [{
            "attributes": {"NMENDCOMP": "RUA OUTRA", "ENDNUMERO": 100,
                           "QUADRA": 55, "LOTE": 66, "SEQIMOVEL": 999},
            "geometry": polygon(),
        }]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    assert search(adapter) == []
    client.close()
    assert adapter.last_diagnostics["Recife"]["result"] == "no_exact_address_match"


def test_recife_unavailable_official_layers_are_reported_as_error(tmp_path):
    urls = []
    def handler(request):
        urls.append(request.url.path)
        raise httpx.ConnectTimeout("municipal origin timed out")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    records = search(adapter)
    client.close()
    assert records == []
    assert len(urls) == 2
    assert adapter.last_diagnostics["Recife"]["result"] == "all_official_services_unavailable"
    assert "Recife" in adapter.last_errors
    assert "ConnectTimeout" in adapter.last_errors["Recife"]


def test_recife_no_number_makes_no_external_request(tmp_path):
    def handler(request):
        raise AssertionError(f"Unbounded query: {request.url}")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    for number in (None, "", "100 OR 1=1"):
        assert search(adapter, number=number) == []
    client.close()


def test_recife_official_endpoints_are_municipal_https():
    assert RECIFE_LOTS.startswith("https://esigportal2.recife.pe.gov.br/")
    assert RECIFE_LOTS_FEATURE.startswith("https://esigportal2.recife.pe.gov.br/")
