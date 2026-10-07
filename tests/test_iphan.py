import json

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.iphan import IPHANAdapter


def test_iphan_maps_heritage_geojson(tmp_path) -> None:
    path = tmp_path / "iphan.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "id_bem": "IPHAN-001",
                            "nome_bem": "Edifício Histórico Exemplo",
                            "tipo_protecao": "Tombamento federal",
                            "processo_tombamento": "1234-T",
                            "municipio": "São Paulo",
                            "uf": "SP",
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

    records = IPHANAdapter(path).search(
        SearchRequest(address="Rua Exemplo", number="10", city="Sao Paulo", state="SP")
    )

    assert len(records) == 1
    record = records[0]
    assert record.property_id == "IPHAN-001"
    assert record.city == "São Paulo"
    assert record.state == "SP"
    assert record.latitude == -23.5505
    assert record.longitude == -46.6333
    assert record.attributes["heritage_name"] == "Edifício Histórico Exemplo"
    assert record.attributes["protection_type"] == "Tombamento federal"
    assert record.attributes["heritage_process"] == "1234-T"
    assert record.provenance[0].source_id == "iphan"


def test_iphan_filters_city_and_state(tmp_path) -> None:
    path = tmp_path / "iphan.csv"
    path.write_text(
        "id_bem,nome_bem,municipio,uf\n"
        "1,Bem SP,Sao Paulo,SP\n"
        "2,Bem RJ,Rio de Janeiro,RJ\n",
        encoding="utf-8",
    )

    records = IPHANAdapter(path).search(
        SearchRequest(address="Qualquer lugar", city="São Paulo", state="SP")
    )
    assert [record.property_id for record in records] == ["1"]


def test_iphan_status_not_configured_without_path() -> None:
    assert IPHANAdapter().status().status == "not_configured"


def test_iphan_rejects_invalid_geojson_shape(tmp_path) -> None:
    path = tmp_path / "iphan.json"
    path.write_text(json.dumps({"features": {}}), encoding="utf-8")

    try:
        IPHANAdapter(path).search(SearchRequest(address="Rua A", number="1"))
    except ValueError as exc:
        assert "list" in str(exc)
    else:
        raise AssertionError("expected ValueError")
