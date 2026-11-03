"""Exact public Caxias municipal parcel and quadra integration."""
import json

import httpx

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.official_municipal_services import OfficialMunicipalServicesAdapter
from imobhunter.sources.rs_caxias_cadastre import CAXIAS_BLOCKS, CAXIAS_LOTS, CAXIAS_MAP_LOTS


def polygon():
    return {"rings": [[
        [-51.1831, -29.1661], [-51.1827, -29.1661],
        [-51.1827, -29.1657], [-51.1831, -29.1661],
    ]]}


def test_caxias_exact_address_official_lot_inscription_and_quadra(tmp_path):
    urls = []

    def handler(request):
        urls.append(request.url.path)
        params = dict(request.url.params)
        assert params["outFields"]
        if "/FeatureServer/3/" in request.url.path:
            assert "ALFREDO" in params["where"] and "'1333'" in params["where"]
            assert params["outSR"] == "4326"
            return httpx.Response(200, json={"features": [{
                "attributes": {
                    "codigolote": 89,
                    "inscricaoloteponto": "A.12.345.678",
                    "nm_logradouro": "ALFREDO CHAVES",
                    "nr_imovel": "1333",
                    "nm_bairro": "EXPOSIÇÃO",
                    "vlr_area_real": 1050.25,
                },
                "geometry": polygon(),
            }, {
                "attributes": {
                    "codigolote": 90, "inscricaoloteponto": "WRONG",
                    "nm_logradouro": "OUTRA RUA", "nr_imovel": "1333",
                },
                "geometry": polygon(),
            }]})
        assert request.url.path.endswith("/FeatureServer/4/query")
        assert params["geometryType"] == "esriGeometryPolygon"
        assert params["spatialRel"] == "esriSpatialRelContains"
        assert json.loads(params["geometry"])["rings"] == polygon()["rings"]
        assert params["inSR"] == "4326"
        assert params["returnGeometry"] == "false"
        return httpx.Response(200, json={"features": [{
            "attributes": {"inscricaonrquadra": 42, "inscricaoquadra": "00042"}
        }]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    result = adapter.search(SearchRequest(
        address="Rua Alfredo Chaves", number="1333",
        city="Caxias do Sul", state="RS",
    ))
    client.close()

    assert len(urls) == 2
    assert len(result) == 1
    lot = result[0]
    assert lot.address == "ALFREDO CHAVES, 1333"
    assert lot.block == "42"
    assert lot.lot is None
    assert lot.area_m2 == 1050.25
    assert lot.attributes["lot_registration_number"] == "A.12.345.678"
    assert lot.attributes["parcel_identifier"] == "A.12.345.678"
    assert lot.attributes["sql"] is None
    assert lot.attributes["iptu_registration_number"] is None
    assert lot.attributes["cadastre_match"] == "exact_address_match"
    assert json.loads(lot.attributes["geometry_geojson"])["type"] == "Polygon"
    assert adapter.last_diagnostics["Caxias do Sul"]["quadra_count"] == 1


def test_caxias_different_street_never_attaches_neighbor_lot(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"features": [{
            "attributes": {
                "nm_logradouro": "RUA TOTALMENTE DIFERENTE", "nr_imovel": "1333",
                "inscricaoloteponto": "DO-NOT-USE",
            },
            "geometry": polygon(),
        }]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    records = adapter.search(SearchRequest(
        address="Rua Alfredo Chaves", number="1333",
        city="Caxias do Sul", state="RS",
    ))
    client.close()
    assert records == []
    assert adapter.last_diagnostics["Caxias do Sul"]["result"] == "no_exact_address_match"


def test_caxias_ambiguous_block_does_not_invent_one(tmp_path):
    def handler(request):
        if "/FeatureServer/3/" in request.url.path:
            return httpx.Response(200, json={"features": [{
                "attributes": {
                    "nm_logradouro": "ALFREDO CHAVES", "nr_imovel": "1333",
                    "inscricaoloteponto": "CODE",
                },
                "geometry": polygon(),
            }]})
        return httpx.Response(200, json={"features": [
            {"attributes": {"inscricaonrquadra": 42}},
            {"attributes": {"inscricaonrquadra": 43}},
        ]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    results = adapter.search(SearchRequest(
        address="Rua Alfredo Chaves", number="1333",
        city="Caxias do Sul", state="RS",
    ))
    client.close()
    assert len(results) == 1
    assert results[0].block is None
    assert results[0].attributes["quadra_match"] == "no_single_official_quadra"


def test_caxias_quadras_timeout_does_not_discard_verified_lot(tmp_path):
    def handler(request):
        if "/FeatureServer/3/" in request.url.path:
            return httpx.Response(200, json={"features": [{
                "attributes": {
                    "nm_logradouro": "ALFREDO CHAVES",
                    "nr_imovel": "1333",
                    "inscricaoloteponto": "TRUSTED-LOT-KEY",
                    "vlr_area_real": 348.5,
                },
                "geometry": polygon(),
            }]})
        raise httpx.ConnectTimeout("quadra municipality unavailable")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    result = adapter.search(SearchRequest(
        address="Rua Alfredo Chaves", number="1333",
        city="Caxias do Sul", state="RS",
    ))
    client.close()
    assert len(result) == 1
    assert result[0].block is None
    assert result[0].attributes["lot_registration_number"] == "TRUSTED-LOT-KEY"
    assert result[0].attributes["quadra_match"] == "quadra_source_error"
    assert result[0].attributes["quadra_diagnostics"]["error_type"] == "ConnectTimeout"
    assert "Caxias do Sul" not in adapter.last_errors


def test_caxias_missing_polygon_never_claims_quadra(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"features": [{
            "attributes": {
                "nm_logradouro": "ALFREDO CHAVES", "nr_imovel": "1333",
                "inscricaoloteponto": "SOURCE-CODE",
            },
        }]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    result = adapter.search(SearchRequest(
        address="Rua Alfredo Chaves", number="1333", city="Caxias do Sul", state="RS",
    ))
    client.close()
    assert len(result) == 1 and result[0].block is None
    assert result[0].attributes["lot_registration_number"] == "SOURCE-CODE"
    assert len(calls) == 1


def test_caxias_requires_street_and_number_and_rejects_injection(tmp_path):
    def handler(_request):
        raise AssertionError("No calls for unbounded requests")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    for number in (None, "1 OR 1=1", "-100", ""):
        assert adapter.search(SearchRequest(
            address="Rua Alfredo Chaves", number=number,
            city="Caxias do Sul", state="RS",
        )) == []
    client.close()


def test_caxias_isolated_from_other_municipalities(tmp_path):
    def handler(_request):
        raise AssertionError("Wrong municipality routed into Caxias")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    assert adapter.search(SearchRequest(
        address="Rua Alfredo Chaves", number="1333", city="Caxias do Sul", state="MG",
    )) == []
    client.close()


def test_caxias_feature_server_timeout_uses_official_mapserver_only(tmp_path):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if "/FeatureServer/3/query" in request.url.path:
            raise httpx.ConnectTimeout("primary source timeout")
        if "/MapServer/3/query" in request.url.path:
            return httpx.Response(200, json={"features": [{
                "attributes": {
                    "nm_logradouro": "ALFREDO CHAVES", "nr_imovel": "1333",
                    "inscricaoloteponto": "12.345.67",
                }, "geometry": polygon(),
            }]})
        return httpx.Response(200, json={"features": [{
            "attributes": {"inscricaonrquadra": 8},
        }]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    records = adapter.search(SearchRequest(
        address="Rua Alfredo Chaves", number="1333",
        city="Caxias do Sul", state="RS",
    ))
    client.close()
    assert len(records) == 1
    assert "/MapServer/3/query" in paths[1]
    assert records[0].block == "8"
    assert records[0].attributes["service_url"] == CAXIAS_MAP_LOTS
    assert records[0].attributes["sql"] is None


def test_caxias_both_official_endpoints_timeout_does_not_fabricate_records(tmp_path):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        raise httpx.ConnectTimeout("origin unavailable")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    records = adapter.search(SearchRequest(
        address="Rua Alfredo Chaves", number="1333",
        city="Caxias do Sul", state="RS",
    ))
    client.close()
    assert records == []
    assert len(paths) == 2
    assert adapter.last_diagnostics["Caxias do Sul"]["result"] == "both_official_lot_services_unavailable"
    assert "Caxias do Sul" in adapter.last_errors
    assert "ConnectTimeout" in adapter.last_errors["Caxias do Sul"]


def test_caxias_endpoints_are_official_https():
    assert CAXIAS_LOTS.startswith("https://gis.caxias.rs.gov.br/")
    assert CAXIAS_BLOCKS.startswith("https://gis.caxias.rs.gov.br/")
