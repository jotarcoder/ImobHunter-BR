import json

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.cnir import CNIRAdapter


def test_cnir_reads_json_and_maps_rural_identifiers(tmp_path) -> None:
    path = tmp_path / "cnir.json"
    path.write_text(
        json.dumps(
            {
                "imoveis": [
                    {
                        "cib": "1234567-8",
                        "codigoImovel": "123456789012",
                        "municipio": "Campinas",
                        "uf": "SP",
                        "areaHectares": 12.5,
                        "situacaoCafir": "ATIVO",
                        "titularNome": "Titular Rural",
                        "titularCpf": "12345678900",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    adapter = CNIRAdapter(path)
    records = adapter.search(SearchRequest(block="1", lot="2", city="Campinas", state="SP"))

    assert len(records) == 1
    record = records[0]
    assert record.cib == "1234567-8"
    assert record.property_id == "1234567-8"
    assert record.area_m2 == 125000
    assert record.owner_name == "Titular Rural"
    assert record.owner_document == "12345678900"
    assert record.attributes["situacaoCafir"] == "ATIVO"
    assert record.attributes["codigo_sncr"] == "123456789012"


def test_cnir_geojson_preserves_geometry(tmp_path) -> None:
    path = tmp_path / "cnir.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "cib": "987",
                            "municipio": "Uberaba",
                            "uf": "MG",
                            "area_total": "2",
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[1, 2], [3, 2], [3, 4], [1, 2]]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    records = CNIRAdapter(path).search(
        SearchRequest(address="Fazenda Exemplo", number="10", city="Uberaba", state="MG")
    )
    assert len(records) == 1
    assert records[0].area_m2 == 20000
    assert records[0].attributes["geometry"]["type"] == "Polygon"


def test_cnir_status_not_configured_without_path() -> None:
    status = CNIRAdapter().status()
    assert status.status == "not_configured"


def test_cnir_rejects_invalid_json_shape(tmp_path) -> None:
    path = tmp_path / "cnir.json"
    path.write_text(json.dumps({"imoveis": {}}), encoding="utf-8")

    adapter = CNIRAdapter(path)
    try:
        adapter.search(SearchRequest(address="Rua A", number="1"))
    except ValueError as exc:
        assert "list of rural properties" in str(exc)
    else:
        raise AssertionError("expected ValueError")
