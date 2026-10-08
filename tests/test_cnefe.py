import json

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.cnefe import CNEFEAdapter


def test_cnefe_geojson_search(tmp_path) -> None:
    path = tmp_path / "cnefe.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-46.66, -23.56]},
                        "properties": {
                            "NM_LOGR": "PAMPLONA",
                            "NUMERO": "1578",
                            "NM_MUNICIPIO": "SAO PAULO",
                            "SIGLA_UF": "SP",
                            "COD_UNICO": "123",
                            "QUADRA": "42",
                            "CEP": "01405000",
                            "NV_GEO_COORD": "Endereco: Coordenada",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    records = CNEFEAdapter(path).search(
        SearchRequest(
            address="Rua Pamplona",
            number="1578",
            city="São Paulo",
            state="SP",
        )
    )

    assert len(records) == 1
    assert records[0].property_id == "123"
    assert records[0].block == "42"
    assert records[0].latitude == -23.56
    assert records[0].longitude == -46.66
    assert records[0].attributes["cep"] == "01405000"
    assert records[0].owner_name is None
    assert records[0].owner_document is None


def test_cnefe_csv_search(tmp_path) -> None:
    path = tmp_path / "cnefe.csv"
    path.write_text(
        "NM_LOGR,NUMERO,NM_MUNICIPIO,SIGLA_UF,COD_UNICO,QUADRA,LATITUDE,LONGITUDE\n"
        "PAMPLONA,1578,SAO PAULO,SP,456,9,-23.5601,-46.6601\n",
        encoding="utf-8",
    )

    records = CNEFEAdapter(path).search(
        SearchRequest(address="Rua Pamplona", number="1578", city="São Paulo", state="SP")
    )

    assert len(records) == 1
    assert records[0].property_id == "456"
    assert records[0].block == "9"


def test_cnefe_reports_missing_local_file(tmp_path) -> None:
    status = CNEFEAdapter(tmp_path / "missing.geojson").status()

    assert status.status == "error"
    assert "not found" in (status.message or "")


def test_cnefe_is_not_configured_without_path(monkeypatch) -> None:
    monkeypatch.delenv("IMOBHUNTER_CNEFE_PATH", raising=False)

    status = CNEFEAdapter().status()

    assert status.status == "not_configured"


def test_cnefe_accepts_list_json(tmp_path) -> None:
    path = tmp_path / "cnefe.json"
    path.write_text(
        json.dumps(
            [
                {
                    "NM_LOGR": "PAMPLONA",
                    "NR_ENDERECO": "1578",
                    "NM_MUNICIPIO": "SAO PAULO",
                    "SIGLA_UF": "SP",
                    "COD_UNICO": "CNEFE-1",
                }
            ]
        ),
        encoding="utf-8",
    )

    records = CNEFEAdapter(path).search(
        SearchRequest(address="Rua Pamplona", number="1578", city="São Paulo", state="SP")
    )

    assert len(records) == 1
    assert records[0].property_id == "CNEFE-1"
    assert records[0].address == "PAMPLONA 1578"
