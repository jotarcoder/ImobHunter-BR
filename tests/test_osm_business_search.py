from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from imobhunter.application.market_intelligence import MarketIntelligenceStore
from imobhunter.application.osm_business_search import fetch_osm_businesses


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "elements": [
                {
                    "type": "node",
                    "id": 123,
                    "lat": -23.55,
                    "lon": -46.63,
                    "tags": {
                        "name": "Padaria Exemplo",
                        "shop": "bakery",
                        "addr:street": "Rua A",
                        "addr:housenumber": "10",
                    },
                },
                {
                    "type": "way",
                    "id": 456,
                    "center": {"lat": -23.56, "lon": -46.64},
                    "tags": {"name": "Clínica Exemplo", "amenity": "clinic"},
                },
                {"type": "node", "id": 789, "lat": "bad", "lon": 0, "tags": {"name": "Inválido"}},
            ]
        }


class FakeClient:
    def __init__(self):
        self.request = None

    def post(self, url, data):
        self.request = (url, data)
        return FakeResponse()


def test_fetch_osm_businesses_parses_nodes_and_way_centers():
    client = FakeClient()
    results = fetch_osm_businesses(-23.55, -46.63, 2, client=client)

    assert len(results) == 2
    assert results[0]["name"] == "Padaria Exemplo"
    assert results[0]["address"] == "Rua A 10"
    assert results[1]["latitude"] == -23.56
    assert "around:2000" in client.request[1]["data"]


@pytest.mark.parametrize("lat,lon,radius", [(91, 0, 1), (0, 181, 1), (0, 0, 0), (0, 0, 26)])
def test_fetch_osm_businesses_rejects_invalid_search(lat, lon, radius):
    with pytest.raises(ValueError):
        fetch_osm_businesses(lat, lon, radius, client=FakeClient())


def test_osm_import_deduplicates_and_radius_search_returns_business(tmp_path: Path):
    store = MarketIntelligenceStore(tmp_path / "market.sqlite3")
    item = {
        "name": "Padaria Exemplo",
        "cnae": "bakery",
        "address": "Rua A 10",
        "latitude": -23.55,
        "longitude": -46.63,
        "source": "OpenStreetMap (node:123)",
    }

    assert store.import_osm_businesses([item]) == 1
    assert store.import_osm_businesses([item]) == 0
    found = store.search_radius(-23.55, -46.63, 2)
    assert len(found) == 1
    assert found[0]["name"] == "Padaria Exemplo"
    assert found[0]["revenue_status"] == "Indisponível"
