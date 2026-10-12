import httpx
import pytest

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.ogc_wfs import ConfigurableWFSAdapter


def test_configurable_wfs_queries_address_and_parses_feature() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"features": [{
            "id": "lot.7",
            "geometry": {"type": "Point", "coordinates": [-46.6, -23.5]},
            "properties": {"id": "7", "logradouro": "Rua A", "numero": "10", "area_m2": "120.5"},
        }]})

    adapter = ConfigurableWFSAdapter(
        endpoint="https://example.test/ows",
        layer="cadastro:lotes",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    records = adapter.search(SearchRequest(address="Rua A", number="10", city="São Paulo", state="SP"))

    assert len(records) == 1
    assert records[0].property_id == "7"
    assert records[0].area_m2 == 120.5
    assert records[0].latitude == pytest.approx(-23.5)
    assert records[0].longitude == pytest.approx(-46.6)
    assert "CQL_FILTER" in captured["url"]
    assert "typeNames=cadastro%3Alotes" in captured["url"]


def test_configurable_wfs_queries_block_and_lot() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"features": []})

    adapter = ConfigurableWFSAdapter(
        endpoint="https://example.test/ows",
        layer="cadastro:lotes",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert adapter.search(SearchRequest(block="02", lot="003", state="SP")) == []
    assert "quadra" in captured["url"]
    assert "lote" in captured["url"]


def test_configurable_wfs_rejects_unsafe_field_names() -> None:
    adapter = ConfigurableWFSAdapter(
        endpoint="https://example.test/ows",
        layer="cadastro:lotes",
        address_field="logradouro OR 1=1",
        client=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"features": []}))),
    )
    with pytest.raises(ValueError, match="Invalid WFS"):
        adapter.search(SearchRequest(address="Rua A"))
