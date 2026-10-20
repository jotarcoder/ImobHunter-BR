from __future__ import annotations

import httpx
import pytest

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.geosampa import DEFAULT_WFS_URL, GeoSampaAdapter


def test_geosampa_search_builds_filtered_wfs_request_and_parses_current_fields() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[
                                [-46.65, -23.57],
                                [-46.649, -23.57],
                                [-46.649, -23.569],
                                [-46.65, -23.569],
                                [-46.65, -23.57],
                            ]],
                        },
                        "properties": {
                            "cd_identificador": "123456",
                            "cd_setor_fiscal": "010",
                            "cd_quadra_fiscal": "020",
                            "cd_lote": "0030",
                            "cd_digito_sql": "1",
                            "nr_contribuinte": "010.020.0030-1",
                            "cd_cib": "ABC123",
                            "nm_logradouro_completo": "R PAMPLONA",
                            "cd_numero_porta": "1578",
                            "qt_area_terreno": "420.5",
                            "qt_area_construida": "210.25",
                            "cd_logradouro": "12345",
                            "cd_condominio": "00",
                            "tx_complemento_endereco": "FUNDOS",
                            "tx_tipo_lote": "FISCAL",
                            "tx_situ_lote": "ATIVO",
                        },
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = GeoSampaAdapter(client=client)

    records = adapter.search(
        SearchRequest(
            address="Rua Pamplona",
            number="1578",
            city="São Paulo",
            state="SP",
        )
    )

    assert len(records) == 1
    assert records[0].city == "SAO PAULO"
    assert records[0].state == "SP"
    assert records[0].block == "020"
    assert records[0].lot == "0030"
    assert records[0].cib == "ABC123"
    assert records[0].area_m2 == 420.5
    assert records[0].latitude == pytest.approx(-23.5696)
    assert records[0].longitude == pytest.approx(-46.6496)
    assert records[0].attributes["sql"] == "010.020.0030-1"
    assert records[0].attributes["iptu_contributor"] is None
    assert records[0].attributes["iptu_registration_number"] == "010.020.0030-1"
    assert records[0].attributes["iptu_current_debt_status"] == "not_provided_by_this_layer"
    assert records[0].attributes["built_area_m2"] == 210.25
    assert records[0].attributes["lot_status"] == "ATIVO"
    assert records[0].attributes["house_number_match"] == "exact"
    assert records[0].attributes["source_attributes"]["cd_numero_porta"] == "1578"
    assert "nm_logradouro_completo" in records[0].attributes["source_attribute_names"]
    assert records[0].attributes["taxpayer_name_status"] == "not_provided_by_this_layer"
    assert records[0].attributes["owner_document_status"] == "not_provided_by_this_layer"
    assert records[0].owner_name is None
    assert records[0].owner_document is None
    assert "typeName=geoportal%3Alote_cidadao" in str(captured["url"])
    assert "nm_logradouro_completo+ILIKE" in str(captured["url"])
    assert "cd_numero_porta" in str(captured["url"])


def test_geosampa_source_status_explains_scope_and_limitations() -> None:
    status = GeoSampaAdapter().status()

    assert status.status == "available"
    assert "SQL/IPTU" in (status.message or "")
    assert "não confirma" in (status.message or "")


def test_geosampa_maps_taxpayer_fields_only_when_source_returns_them() -> None:
    adapter = GeoSampaAdapter()
    records = adapter._parse_features({
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-46.65, -23.57]},
            "properties": {
                "nr_contribuinte": "010.020.0030-1",
                "nm_contribuinte": "Titular fornecido pela fonte",
                "nr_cpf_cnpj": "documento-mascarado",
            },
        }]
    })

    assert records[0].attributes["taxpayer_name_status"] == "provided_by_source"
    assert records[0].attributes["owner_document_status"] == "provided_by_source"
    # Values are not copied into legal-owner fields: the source field is a
    # taxpayer attribute, not proof of current registered ownership.
    assert records[0].owner_name is None
    assert records[0].owner_document is None


def test_geosampa_address_only_search_returns_candidate_parcels() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"features": []}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = GeoSampaAdapter(client=client)
    adapter.search(SearchRequest(address="Rua Pamplona", city="São Paulo", state="SP"))

    assert "nm_logradouro_completo" in captured["url"]
    assert "cd_numero_porta" not in captured["url"]


def test_geosampa_ignores_non_sao_paulo_states() -> None:
    adapter = GeoSampaAdapter(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"features": []})
            )
        )
    )

    records = adapter.search(
        SearchRequest(address="Rua Pamplona", number="1578", state="RJ")
    )

    assert records == []


def test_geosampa_surfaces_http_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request, text="unavailable")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = GeoSampaAdapter(client=client)

    try:
        adapter.search(
            SearchRequest(
                address="Rua Pamplona",
                number="1578",
                city="São Paulo",
                state="SP",
            )
        )
    except RuntimeError as exc:
        assert "GeoSampa request failed" in str(exc)
    else:
        raise AssertionError("expected GeoSampa HTTP failure")


def test_geosampa_surfaces_invalid_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, text="not-json")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = GeoSampaAdapter(client=client)

    try:
        adapter.search(
            SearchRequest(
                address="Rua Pamplona",
                number="1578",
                city="São Paulo",
                state="SP",
            )
        )
    except RuntimeError as exc:
        assert "GeoSampa: WFS devolveu conteúdo que não é JSON válido" in str(exc)
        assert "HTTP 200" in str(exc)
    else:
        raise AssertionError("expected GeoSampa JSON failure")


def test_geosampa_search_by_fiscal_block_and_lot() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"features": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = GeoSampaAdapter(client=client)

    records = adapter.search(
        SearchRequest(block="020", lot="0030", city="São Paulo", state="SP")
    )

    assert records == []
    assert "cd_quadra_fiscal" in captured["url"]
    assert "cd_lote" in captured["url"]
    assert "020" in captured["url"]
    assert "0030" in captured["url"]



def test_geosampa_falls_back_to_street_when_exact_house_number_has_no_match() -> None:
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cql = request.url.params.get("CQL_FILTER", "")
        captured.append(cql)
        if "cd_numero_porta" in cql:
            return httpx.Response(200, json={"features": []}, request=request)
        return httpx.Response(
            200,
            json={
                "features": [{
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-46.65, -23.57]},
                    "properties": {
                        "cd_setor_fiscal": "010",
                        "cd_quadra_fiscal": "020",
                        "cd_lote": "0030",
                        "cd_digito_sql": "1",
                        "nm_logradouro_completo": "R PAMPLONA",
                    },
                }]
            },
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    records = GeoSampaAdapter(client=client).search(
        SearchRequest(address="Rua Pamplona", number="1578", city="São Paulo", state="SP")
    )

    assert len(records) == 1
    assert len(captured) == 3
    assert "cd_numero_porta='1578'" in captured[0]
    assert "cd_numero_porta=1578" in captured[1]
    assert "cd_numero_porta" not in captured[2]
    assert records[0].attributes["house_number_match"] == "candidate_only"
    assert records[0].attributes["iptu_contributor"] is None
    assert records[0].attributes["iptu_registration_number"] == "010.020.0030-1"
    assert records[0].attributes["iptu_current_debt_status"] == "not_provided_by_this_layer"
    assert records[0].attributes["house_number_match"] == "candidate_only"


def test_geosampa_retries_numeric_house_number_filter_before_street_fallback() -> None:
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cql = request.url.params.get("CQL_FILTER", "")
        captured.append(cql)
        if "cd_numero_porta=1578" in cql:
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [{
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-46.65, -23.57]},
                        "properties": {
                            "cd_numero_porta": 1578,
                            "cd_quadra_fiscal": "020",
                            "cd_lote": "0030",
                            "nr_contribuinte": "010.020.0030-1",
                            "nm_logradouro_completo": "R PAMPLONA",
                        },
                    }],
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={"type": "FeatureCollection", "features": []},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    records = GeoSampaAdapter(client=client).search(
        SearchRequest(address="Rua Pamplona", number="1578", city="São Paulo", state="SP")
    )

    assert len(captured) == 2
    assert "cd_numero_porta='1578'" in captured[0]
    assert "cd_numero_porta=1578" in captured[1]
    assert len(records) == 1
    assert records[0].attributes["house_number_match"] == "exact"
    assert records[0].attributes["door_number"] == "1578"


def test_geosampa_uses_geocoded_point_to_select_parcel_when_number_filter_misses() -> None:
    captured: list[dict[str, str]] = []

    class FakeGeocoder:
        def geocode(self, address: str) -> dict[str, object]:
            return {
                "latitude": -23.57,
                "longitude": -46.65,
                "provider": "test-geocoder",
                "display_name": address,
            }

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        captured.append(params)
        if "bbox" not in params:
            return httpx.Response(
                200,
                json={"type": "FeatureCollection", "features": []},
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [-46.651, -23.571],
                            [-46.649, -23.571],
                            [-46.649, -23.569],
                            [-46.651, -23.569],
                            [-46.651, -23.571],
                        ]],
                    },
                    "properties": {
                        "cd_numero_porta": "1578",
                        "cd_quadra_fiscal": "020",
                        "cd_lote": "0030",
                        "nr_contribuinte": "010.020.0030-1",
                        "nm_logradouro_completo": "R PAMPLONA",
                        "qt_area_terreno": 420,
                    },
                }],
            },
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    records = GeoSampaAdapter(client=client, geocoder=FakeGeocoder()).search(
        SearchRequest(address="Rua Pamplona", number="1578", city="São Paulo", state="SP")
    )

    assert len(records) == 1
    assert len(captured) == 4
    assert "bbox" in captured[-1]
    assert records[0].attributes["house_number_match"] == "geocoded_spatial_match"
    assert records[0].attributes["address_geocoding_provider"] == "test-geocoder"
    assert records[0].attributes["source_attributes"]["cd_numero_porta"] == "1578"
    assert records[0].block == "020"
    assert records[0].lot == "0030"


def test_geosampa_uses_official_wfs_endpoint_path() -> None:
    assert DEFAULT_WFS_URL == "https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs"
    assert GeoSampaAdapter().layer == "geoportal:lote_cidadao"



def test_geosampa_keeps_taxpayer_name_separate_from_registration_number() -> None:
    records = GeoSampaAdapter()._parse_features({
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-46.65, -23.57]},
            "properties": {
                "nr_contribuinte": "010.020.0030-1",
                "nm_contribuinte": "Nome de contribuinte fornecido pela fonte",
                "ano_base": "2016",
            },
        }]
    })
    attributes = records[0].attributes
    assert attributes["iptu_contributor"] == "Nome de contribuinte fornecido pela fonte"
    assert attributes["iptu_registration_number"] == "010.020.0030-1"
    assert attributes["iptu_reference_year"] == "2016"
    assert attributes["iptu_data_scope"] == "historical"
    assert attributes["iptu_current_debt_status"] == "not_provided_by_this_layer"
    assert records[0].owner_name is None



def test_geosampa_preserves_polygon_geojson_for_cadastral_map() -> None:
    geometry = {
        "type": "Polygon",
        "coordinates": [[[-46.65, -23.57], [-46.64, -23.57], [-46.64, -23.56], [-46.65, -23.57]]],
    }
    records = GeoSampaAdapter()._parse_features({
        "features": [{"type": "Feature", "geometry": geometry, "properties": {"cd_lote": "0030"}}]
    })
    import json
    assert json.loads(records[0].attributes["geometry_geojson"]) == geometry


def test_geosampa_rejects_unsupported_geometry_for_map() -> None:
    records = GeoSampaAdapter()._parse_features({
        "features": [{"type": "Feature", "geometry": {"type": "GeometryCollection", "geometries": []}, "properties": {}}]
    })
    assert records[0].attributes["geometry_geojson"] is None


def test_geosampa_wildcards_each_street_token_for_source_abbreviations() -> None:
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.url.params.get("CQL_FILTER", ""))
        return httpx.Response(200, json={"features": []}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    GeoSampaAdapter(client=client).search(
        SearchRequest(address="Rua Doutor Arnaldo", number="100", city="São Paulo", state="SP")
    )

    assert len(captured) == 3
    assert "nm_logradouro_completo ILIKE '%ARNALDO%'" in captured[0]
    assert "cd_numero_porta='100'" in captured[0]
    assert "nm_logradouro_completo ILIKE '%ARNALDO%'" in captured[1]
    assert "cd_numero_porta=100" in captured[1]
    assert "nm_logradouro_completo ILIKE '%ARNALDO%'" in captured[2]
    assert "cd_numero_porta" not in captured[2]


def test_geosampa_returns_empty_list_for_valid_empty_geojson() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"type": "FeatureCollection", "features": []}, request=request)
        )
    )
    records = GeoSampaAdapter(client=client).search(
        SearchRequest(address="Rua Pamplona", city="São Paulo", state="SP")
    )
    assert records == []


def test_geosampa_uses_live_public_wfs_endpoint_and_parameters() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    GeoSampaAdapter(client=client).search(
        SearchRequest(address="Av Paulista", city="São Paulo", state="SP")
    )
    assert str(captured["url"]).startswith("https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs?")
    params = captured["params"]
    assert params["service"] == "WFS"
    assert params["request"] == "GetFeature"
    assert params["typeName"] == "geoportal:lote_cidadao"
    assert params["outputFormat"] == "json"
    assert params["srsName"] == "EPSG:4326"


def test_geosampa_fails_closed_when_city_or_state_is_missing() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = GeoSampaAdapter(client=client)

    assert adapter.search(SearchRequest(address="Rua Exemplo", city="São Paulo")) == []
    assert adapter.search(SearchRequest(address="Rua Exemplo", state="SP")) == []
    assert adapter.search(SearchRequest(address="Rua Exemplo", city="Santos", state="SP")) == []
    assert adapter.search(SearchRequest(address="Rua Exemplo", city="São Paulo", state="RJ")) == []
    assert calls == []
    client.close()
