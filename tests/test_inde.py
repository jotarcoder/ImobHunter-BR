import json

import pytest

from imobhunter.sources.inde import INDECatalog


def test_inde_searches_json_catalog(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "services": [
                    {
                        "id": "sp-urban",
                        "name": "Cadastro urbano",
                        "provider": "Município",
                        "type": "WFS",
                        "url": "https://example.test/wfs",
                        "type_name": "urban:lotes",
                        "keywords": ["lotes", "cadastro"],
                        "uf": "SP",
                        "municipality": "São Paulo",
                    },
                    {
                        "id": "rj-map",
                        "name": "Mapa",
                        "type": "WMS",
                        "uf": "RJ",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    catalog = INDECatalog(path)
    result = catalog.search(text="lotes", state="SP", service_type="WFS")

    assert len(result) == 1
    assert result[0].service_id == "sp-urban"
    assert result[0].layer == "urban:lotes"


def test_inde_reads_csv_keywords(tmp_path):
    path = tmp_path / "catalog.csv"
    path.write_text(
        "service_id,title,provider,service_type,url,layer,keywords,state,city\n"
        "1,Cadastro,Prefeitura,WFS,https://example.test,wfs:lotes,lotes\, cadastro,SP,Santos\n",
        encoding="utf-8",
    )

    result = INDECatalog(path).search(city="Santos")

    assert len(result) == 1
    assert result[0].keywords == ("lotes", "cadastro")


def test_inde_not_configured():
    catalog = INDECatalog()
    assert catalog.status() == "not_configured"
    assert catalog.search(text="lotes") == []


def test_inde_rejects_unknown_format(tmp_path):
    path = tmp_path / "catalog.txt"
    path.write_text("x", encoding="utf-8")

    with pytest.raises(ValueError, match="CSV or JSON"):
        INDECatalog(path).load()
