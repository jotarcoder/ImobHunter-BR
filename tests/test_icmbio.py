import json

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.icmbio import ICMBioAdapter


def test_icmbio_maps_conservation_unit_geojson(tmp_path) -> None:
    path = tmp_path / "icmbio.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "id_uc": "UC-001",
                            "nome_uc": "Parque Nacional Exemplo",
                            "categoria": "Parque Nacional",
                            "municipio": "São Paulo",
                            "uf": "SP",
                            "bioma": "Mata Atlântica",
                            "area_ha": 12.5,
                            "gestao": "ICMBio",
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

    records = ICMBioAdapter(path).search(
        SearchRequest(address="Rua Exemplo", number="10", city="Sao Paulo", state="SP")
    )

    assert len(records) == 1
    record = records[0]
    assert record.property_id == "UC-001"
    assert record.city == "São Paulo"
    assert record.state == "SP"
    assert record.area_m2 == 125000
    assert record.latitude == -23.5505
    assert record.longitude == -46.6333
    assert record.attributes["environmental_name"] == "Parque Nacional Exemplo"
    assert record.attributes["environmental_category"] == "Parque Nacional"
    assert record.provenance[0].source_id == "icmbio"


def test_icmbio_filters_city_and_state(tmp_path) -> None:
    path = tmp_path / "icmbio.csv"
    path.write_text(
        "id_uc,nome_uc,municipio,uf,area_ha\n"
        "1,UC SP,Sao Paulo,SP,1\n"
        "2,UC RJ,Rio de Janeiro,RJ,2\n",
        encoding="utf-8",
    )

    records = ICMBioAdapter(path).search(
        SearchRequest(address="Qualquer lugar", city="São Paulo", state="SP")
    )
    assert [record.property_id for record in records] == ["1"]


def test_icmbio_status_not_configured_without_path() -> None:
    assert ICMBioAdapter().status().status == "not_configured"


def test_icmbio_rejects_invalid_json_shape(tmp_path) -> None:
    path = tmp_path / "icmbio.json"
    path.write_text(json.dumps({"features": {}}), encoding="utf-8")

    try:
        ICMBioAdapter(path).search(SearchRequest(address="Rua A", number="1"))
    except ValueError as exc:
        assert "list" in str(exc)
    else:
        raise AssertionError("expected ValueError")
