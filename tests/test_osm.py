import json

import pytest

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.osm import OSMAdapter


def test_osm_maps_geojson_feature(tmp_path) -> None:
    path = tmp_path / "osm.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "osm_id": "node/123",
                            "name": "Praça Exemplo",
                            "amenity": "cafe",
                            "addr:street": "Rua Exemplo",
                            "addr:housenumber": "10",
                            "addr:city": "São Paulo",
                            "addr:state": "SP",
                        },
                        "geometry": {
                            "type": "Point",
                            "coordinates": [-46.6333, -23.5505],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    records = OSMAdapter(path).search(
        SearchRequest(address="Rua Exemplo", number="10", city="Sao Paulo", state="SP")
    )

    assert len(records) == 1
    record = records[0]
    assert record.property_id == "osm:node/123"
    assert record.address == "Rua Exemplo, 10"
    assert record.city == "São Paulo"
    assert record.state == "SP"
    assert record.latitude == -23.5505
    assert record.longitude == -46.6333
    assert record.attributes["osm_name"] == "Praça Exemplo"
    assert record.attributes["osm_category"] == "cafe"
    assert record.provenance[0].reference.endswith("/copyright")


def test_osm_filters_city_and_state(tmp_path) -> None:
    path = tmp_path / "osm.csv"
    path.write_text(
        "osm_id,name,municipio,uf,addr:street,addr:housenumber\n"
        "1,Ponto SP,Sao Paulo,SP,Rua A,1\n"
        "2,Ponto RJ,Rio de Janeiro,RJ,Rua A,1\n",
        encoding="utf-8",
    )

    records = OSMAdapter(path).search(
        SearchRequest(address="Rua A", number="1", city="São Paulo", state="SP")
    )
    assert [record.property_id for record in records] == ["osm:1"]


def test_osm_status_not_configured_without_path() -> None:
    assert OSMAdapter().status().status == "not_configured"


def test_osm_rejects_invalid_geojson_shape(tmp_path) -> None:
    path = tmp_path / "osm.geojson"
    path.write_text(json.dumps({"features": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="features"):
        OSMAdapter(path).search(SearchRequest(address="Rua A", number="1"))
