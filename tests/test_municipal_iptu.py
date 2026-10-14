import json

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.municipal_iptu import MunicipalIPTUAdapter


def test_iptu_maps_debts_and_query_state(tmp_path) -> None:
    path = tmp_path / "iptu.json"
    path.write_text(json.dumps([{
        "sql": "123.456.7890-1",
        "endereco": "Rua Exemplo",
        "municipio": "São Paulo",
        "uf": "SP",
        "contribuinte": "Contribuinte Exemplo",
        "query_status": "debt_found",
        "query_date": "2026-10-07",
        "official_source": "https://iptu.prefeitura.sp.gov.br/",
        "tax_debts": [{"status": "overdue", "year": 2026, "amount": 123.45}]
    }]), encoding="utf-8")
    records = MunicipalIPTUAdapter(path).search(
        SearchRequest(address="Rua Exemplo", city="São Paulo", state="SP")
    )
    assert len(records) == 1
    assert records[0].property_id == "123.456.7890-1"
    assert records[0].tax_debts[0].amount == 123.45
    assert records[0].attributes["iptu_query_status"] == "debt_found"


def test_iptu_not_configured() -> None:
    assert MunicipalIPTUAdapter().status().status == "not_configured"



def test_iptu_taxpayer_is_not_mislabeled_as_legal_owner_and_missing_status_is_not_no_debt(tmp_path) -> None:
    path = tmp_path / "iptu.csv"
    path.write_text(
        "sql,endereco,municipio,uf,contribuinte,ano_base\n"
        "010.020.0030-1,Rua Exemplo,São Paulo,SP,Nome do Contribuinte,2016\n",
        encoding="utf-8",
    )
    records = MunicipalIPTUAdapter(path).search(
        SearchRequest(address="Rua Exemplo", city="São Paulo", state="SP")
    )

    assert len(records) == 1
    assert records[0].owner_name is None
    assert records[0].attributes["taxpayer_name"] == "Nome do Contribuinte"
    assert records[0].attributes["taxpayer_name_status"] == "provided_by_source"
    assert records[0].attributes["iptu_reference_year"] == 2016
    assert records[0].attributes["iptu_data_scope"] == "historical"
    assert records[0].attributes["iptu_query_status"] == "not_verified"
    assert records[0].attributes["iptu_current_debt_status"] == "not_verified"
