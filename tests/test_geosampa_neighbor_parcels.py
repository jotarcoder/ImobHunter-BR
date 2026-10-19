from __future__ import annotations

import httpx

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.geosampa import GeoSampaAdapter


def test_geosampa_keeps_neighboring_official_parcels_for_map_context() -> None:
    class FakeGeocoder:
        def geocode(self, address: str) -> dict[str, object]:
            return {
                "latitude": -23.57,
                "longitude": -46.65,
                "provider": "test-geocoder",
                "display_name": address,
            }

    def polygon(west: float, east: float) -> dict[str, object]:
        return {
            "type": "Polygon",
            "coordinates": [[
                [west, -23.571], [east, -23.571], [east, -23.569],
                [west, -23.569], [west, -23.571],
            ]],
        }

    def handler(request: httpx.Request) -> httpx.Response:
        if "bbox" not in request.url.params:
            return httpx.Response(200, json={"type": "FeatureCollection", "features": []}, request=request)
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": polygon(-46.651, -46.649), "properties": {
                    "cd_numero_porta": "1578", "cd_quadra_fiscal": "020",
                    "cd_lote": "0030", "nr_contribuinte": "010.020.0030-1",
                }},
                {"type": "Feature", "geometry": polygon(-46.649, -46.647), "properties": {
                    "cd_numero_porta": "1580", "cd_quadra_fiscal": "020",
                    "cd_lote": "0031", "nr_contribuinte": "010.020.0031-0",
                }},
            ],
        }, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    records = GeoSampaAdapter(client=client, geocoder=FakeGeocoder()).search(
        SearchRequest(address="Rua Pamplona", number="1578", city="São Paulo", state="SP")
    )

    assert len(records) == 2
    target = next(record for record in records if record.lot == "0030")
    neighbor = next(record for record in records if record.lot == "0031")
    assert target.attributes["house_number_match"] == "geocoded_spatial_match"
    assert neighbor.attributes["house_number_match"] == "neighboring_parcel"
    assert neighbor.attributes["parcel_relation"] == "neighbor_candidate"
    assert neighbor.attributes["geometry_geojson"]
