import json

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.sinter import SINTERAdapter


def test_sinter_geojson_search_by_block_and_lot(tmp_path) -> None:
    path = tmp_path / "sinter.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-46.66, -23.56]},
                        "properties": {
                            "CIB": "ABC1234-5",
                            "MUNICIPIO": "SAO PAULO",
                            "UF": "SP",
                            "QUADRA": "42",
                            "LOTE": "17",
                            "AREA_M2": "320.5",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    records = SINTERAdapter(path).search(
        SearchRequest(city="São Paulo", state="SP", block="42", lot="17")
    )

    assert len(records) == 1
    assert records[0].cib == "ABC1234-5"
    assert records[0].block == "42"
    assert records[0].lot == "17"
    assert records[0].area_m2 == 320.5
    assert records[0].provenance[0].source_id == "sinter_cib"


def test_sinter_csv_search_by_address(tmp_path) -> None:
    path = tmp_path / "sinter.csv"
    path.write_text(
        "CIB,ENDERECO,NUMERO,MUNICIPIO,UF,QUADRA,LOTE\n"
        "XYZ9876-1,PAMPLONA,1578,SAO PAULO,SP,9,12\n",
        encoding="utf-8",
    )

    records = SINTERAdapter(path).search(
        SearchRequest(
            address="Rua Pamplona",
            number="1578",
            city="São Paulo",
            state="SP",
        )
    )

    assert len(records) == 1
    assert records[0].cib == "XYZ9876-1"
    assert records[0].block == "9"
    assert records[0].lot == "12"


def test_sinter_reports_missing_local_file(tmp_path) -> None:
    status = SINTERAdapter(tmp_path / "missing.json").status()

    assert status.status == "error"
    assert "not found" in (status.message or "")


def test_sinter_is_not_configured_without_path(monkeypatch) -> None:
    monkeypatch.delenv("IMOBHUNTER_SINTER_CIB_PATH", raising=False)

    status = SINTERAdapter().status()

    assert status.status == "not_configured"


def test_sinter_authenticated_cib_lookup(monkeypatch) -> None:
    payload = {
        "InfoIbge": {"nomeMunicipio": "Belo Horizonte", "siglaUf": "MG", "codigoIbge": 3106200},
        "Cib": {"valor": "CJNJJ50G", "situacao": "Ativa"},
        "DadosGeraisImovel": {
            "inscricaoImobiliaria": "123456",
            "areaTerreno": 350.75,
            "areaConstruida": 120.5,
            "valorVenal": 450000,
        },
        "EnderecoImovel": {"nomeLogradouro": "Avenida Brasil", "numeroImovel": "1234", "cep": "70040900"},
        "Titular": [{"nomeTitular": "JOAO DA SILVA", "niTitular": "12345678901"}],
    }

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return payload

    def fake_get(url, *, headers, timeout):
        assert url.endswith("/api/v1/ui/CJNJJ50G")
        assert headers["Authorization"] == "Bearer test-token"
        assert timeout == 20.0
        return FakeResponse()

    monkeypatch.setenv("IMOBHUNTER_SINTER_API_BASE_URL", "https://sinter.test")
    monkeypatch.setenv("IMOBHUNTER_SINTER_API_TOKEN", "test-token")
    monkeypatch.setattr("imobhunter.sources.sinter.httpx.get", fake_get)

    records = SINTERAdapter().search(SearchRequest(cib="CJNJJ50G"))

    assert len(records) == 1
    assert records[0].cib == "CJNJJ50G"
    assert records[0].owner_name == "JOAO DA SILVA"
    assert records[0].owner_document == "12345678901"
    assert records[0].area_m2 == 350.75
    assert records[0].attributes["valor_venal"] == 450000


def test_sinter_api_status_requires_both_credentials(monkeypatch) -> None:
    monkeypatch.setenv("IMOBHUNTER_SINTER_API_BASE_URL", "https://sinter.test")
    monkeypatch.delenv("IMOBHUNTER_SINTER_API_TOKEN", raising=False)

    status = SINTERAdapter().status()

    assert status.status == "not_configured"
