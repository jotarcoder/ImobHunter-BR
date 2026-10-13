from __future__ import annotations

import httpx
import pytest

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.geosampa import GeoSampaAdapter


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
    assert records[0].attributes["iptu_contributor"] == "010.020.0030-1"
    assert records[0].attributes["built_area_m2"] == 210.25
    assert records[0].attributes["lot_status"] == "ATIVO"
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
        assert str(exc) == "GeoSampa returned invalid JSON"
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
