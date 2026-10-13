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
        '1,Cadastro,Prefeitura,WFS,https://example.test,wfs:lotes,"lotes, cadastro",SP,Santos\n',
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


def test_inde_remote_csw_search_parses_records_and_uses_query() -> None:
    from imobhunter.sources.inde import DEFAULT_INDE_CSW_ENDPOINT
    import httpx

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(200, text="""<?xml version="1.0"?>
        <csw:GetRecordsResponse xmlns:csw="http://www.opengis.net/cat/csw/2.0.2"
          xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dct="http://purl.org/dc/terms/">
          <csw:SearchResults numberOfRecordsMatched="1">
            <csw:Record>
              <dc:identifier>inde-123</dc:identifier>
              <dc:title>Cadastro municipal de lotes</dc:title>
              <dc:creator>Prefeitura</dc:creator>
              <dc:subject>cadastro</dc:subject>
              <dct:references scheme="OGC:WFS">https://geo.example.gov/ows</dct:references>
              <dc:date>2026-01-01</dc:date>
            </csw:Record>
          </csw:SearchResults>
        </csw:GetRecordsResponse>""")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = INDECatalog.search_remote("cadastro", client=client)

    assert DEFAULT_INDE_CSW_ENDPOINT in captured["url"]
    assert "cadastro" in captured["body"]
    assert len(result) == 1
    assert result[0].service_id == "inde-123"
    assert result[0].service_type == "WFS"
    assert result[0].url == "https://geo.example.gov/ows"
