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
