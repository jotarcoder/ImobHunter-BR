import json

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.sncr import SNCRAdapter


def test_sncr_searches_json_by_location(tmp_path):
    path = tmp_path / "sncr.json"
    path.write_text(
        json.dumps(
            {
                "imoveis": [
                    {
                        "codigoImovel": "7090260272785",
                        "nomeImovelRural": "FAZENDA TESTE",
                        "localizacaoImovelRural": "BR 101 KM 15",
                        "municipio": "Itaborai",
                        "uf": "RJ",
                        "areaTotal": 12.5,
                        "situacaoImovel": "Ativo",
                        "nome_titular": "Titular Teste",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = SNCRAdapter(path).search(
        SearchRequest(address="BR 101 KM 15", city="Itaborai", state="RJ")
    )

    assert len(result) == 1
    assert result[0].property_id == "7090260272785"
    assert result[0].area_m2 == 125000
    assert result[0].owner_name == "Titular Teste"


def test_sncr_reads_csv(tmp_path):
    path = tmp_path / "sncr.csv"
    path.write_text(
        "codigo_imovel,localizacao_imovel_rural,municipio,uf,area_total\n"
        "123,ESTRADA TESTE,Campinas,SP,2.5\n",
        encoding="utf-8",
    )

    result = SNCRAdapter(path).search(
        SearchRequest(address="Estrada Teste", city="Campinas", state="SP")
    )

    assert len(result) == 1
    assert result[0].area_m2 == 25000


def test_sncr_not_configured():
    adapter = SNCRAdapter()
    assert adapter.status().status == "not_configured"
    assert adapter.search(SearchRequest(address="x")) == []
