from __future__ import annotations

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.national_geocoder import NationalAddressGeocoderAdapter


class FakeGeocoder:
    def __init__(self, result=None, error=None):
        self.result = result or {
            "latitude": -24.004354,
            "longitude": -46.413148,
            "display_name": "Avenida Costa e Silva, Praia Grande, Brasil",
            "provider": "OpenStreetMap Nominatim",
            "attribution": "© OpenStreetMap contributors",
            "cached": False,
        }
        self.error = error
        self.queries = []

    def geocode(self, query):
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.result


def test_national_geocoder_returns_point_and_explicitly_no_cadastral_data():
    geocoder = FakeGeocoder()
    adapter = NationalAddressGeocoderAdapter(geocoder=geocoder)
    records = adapter.search(SearchRequest(
        address="Avenida Presidente Costa e Silva",
        city="Praia Grande",
        state="SP",
    ))

    assert len(records) == 1
    record = records[0]
    assert record.latitude == -24.004354
    assert record.longitude == -46.413148
    assert record.attributes["record_kind"] == "geocoded_address_only"
    assert record.attributes["parcel_status"] == "not_provided_by_geocoder"
    assert record.attributes["sql_status"] == "not_provided_by_geocoder"
    assert record.attributes["owner_status"] == "not_provided_by_geocoder"
    assert record.attributes["map_attribution"] == "© OpenStreetMap contributors"
    assert geocoder.queries == [
        "Avenida Presidente Costa e Silva, Praia Grande, SP, Brasil"
    ]


def test_national_geocoder_does_not_duplicate_sao_paulo_city_geosampa_results():
    geocoder = FakeGeocoder()
    adapter = NationalAddressGeocoderAdapter(geocoder=geocoder)
    records = adapter.search(SearchRequest(
        address="Avenida Paulista",
        number="1000",
        city="São Paulo",
        state="SP",
    ))
    assert records == []
    assert geocoder.queries == []


def test_national_geocoder_requires_city_state_and_address():
    geocoder = FakeGeocoder()
    adapter = NationalAddressGeocoderAdapter(geocoder=geocoder)
    assert adapter.search(SearchRequest(address="Avenida Brasil", city="Rio de Janeiro")) == []
    assert geocoder.queries == []
