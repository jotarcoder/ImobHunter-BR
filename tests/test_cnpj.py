import json

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.cnpj import CNPJAdapter


def test_cnpj_maps_company_and_status(tmp_path) -> None:
    path = tmp_path / "cnpj.json"
    path.write_text(
        json.dumps(
            {
                "estabelecimentos": [
                    {
                        "cnpj": "12.345.678/0001-90",
                        "razao_social": "Empresa Rural Ltda",
                        "nome_fantasia": "Fazenda Exemplo",
                        "tipo_logradouro": "RODOVIA",
                        "logradouro": "BR 101",
                        "numero": "1000",
                        "municipio": "Itabuna",
                        "uf": "BA",
                        "situacao_cadastral": "ATIVA",
                        "cnae_principal": "0111-3/01",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    records = CNPJAdapter(path).search(
        SearchRequest(address="Rodovia BR 101", number="1000", city="Itabuna", state="BA")
    )

    assert len(records) == 1
    record = records[0]
    assert record.property_id == "12.345.678/0001-90"
    assert record.owner_name == "Empresa Rural Ltda"
    assert record.owner_document == "12.345.678/0001-90"
    assert record.attributes["company_name"] == "Empresa Rural Ltda"
    assert record.attributes["situacao_cadastral"] == "ATIVA"


def test_cnpj_matches_accented_city(tmp_path) -> None:
    path = tmp_path / "cnpj.csv"
    path.write_text(
        "cnpj,razao_social,logradouro,numero,municipio,uf\n"
        "123,Empresa SA,Rua São João,10,São Paulo,SP\n",
        encoding="utf-8",
    )

    records = CNPJAdapter(path).search(
        SearchRequest(address="Rua Sao Joao", number="10", city="Sao Paulo", state="SP")
    )
    assert len(records) == 1


def test_cnpj_status_not_configured_without_path() -> None:
    assert CNPJAdapter().status().status == "not_configured"


def test_cnpj_rejects_invalid_json_shape(tmp_path) -> None:
    path = tmp_path / "cnpj.json"
    path.write_text(json.dumps({"estabelecimentos": {}}), encoding="utf-8")

    try:
        CNPJAdapter(path).search(SearchRequest(address="Rua A", number="1"))
    except ValueError as exc:
        assert "list of establishments" in str(exc)
    else:
        raise AssertionError("expected ValueError")
