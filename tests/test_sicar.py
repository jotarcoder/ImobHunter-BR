import json

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.sicar import SICARAdapter


def test_sicar_searches_json_by_location(tmp_path):
    path = tmp_path / "sicar.json"
    path.write_text(
        json.dumps(
            {
                "imoveis": [
                    {
                        "codigoImovel": "CAR-RJ-TESTE",
                        "municipio": "Itaborai",
                        "uf": "RJ",
                        "areaTotalImovel": 12.5,
                        "statusImovel": "AT",
                        "tipoImovel": "IRU",
                        "endereco": "ESTRADA TESTE KM 10",
                        "nomeTitular": "Titular Teste",
                        "adesaoPRA": "SIM",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = SICARAdapter(path).search(
        SearchRequest(address="Estrada Teste KM 10", city="Itaborai", state="RJ")
    )

    assert len(result) == 1
    assert result[0].property_id == "CAR-RJ-TESTE"
    assert result[0].area_m2 == 125000
    assert result[0].owner_name == "Titular Teste"
    assert result[0].attributes["statusImovel"] == "AT"


def test_sicar_reads_geojson(tmp_path):
    path = tmp_path / "sicar.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "codigoCAR": "CAR-SP-001",
                            "municipio": "Campinas",
                            "uf": "SP",
                            "areaTotal": 2.5,
                            "enderecoImovel": "ESTRADA TESTE",
                        },
                        "geometry": {"type": "Polygon", "coordinates": []},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = SICARAdapter(path).search(
        SearchRequest(address="Estrada Teste", city="Campinas", state="SP")
    )

    assert len(result) == 1
    assert result[0].property_id == "CAR-SP-001"
    assert result[0].area_m2 == 25000
    assert result[0].attributes["geometry"]["type"] == "Polygon"


def test_sicar_reads_csv(tmp_path):
    path = tmp_path / "sicar.csv"
    path.write_text(
        "codigo_car,endereco,municipio,uf,area_total\n"
        "CAR-001,ESTRADA TESTE,Campinas,SP,2.5\n",
        encoding="utf-8",
    )

    result = SICARAdapter(path).search(
        SearchRequest(address="Estrada Teste", city="Campinas", state="SP")
    )

    assert len(result) == 1
    assert result[0].area_m2 == 25000


def test_sicar_not_configured():
    adapter = SICARAdapter()
    assert adapter.status().status == "not_configured"
    assert adapter.search(SearchRequest(address="x")) == []


def test_sicar_authenticated_car_lookup(monkeypatch):
    payload = {
        "codigoImovel": "BA-176934-20170113-TEST",
        "municipio": "Barreiras",
        "uf": "BA",
        "areaTotalImovel": 10.5,
        "statusImovel": "AT",
        "tipoImovel": "IRU",
        "enderecoImovel": "FAZENDA TESTE",
    }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    def fake_get(url, *, headers, timeout):
        assert url.endswith("/BA-176934-20170113-TEST")
        assert headers["Authorization"] == "Bearer token"
        assert timeout == 20.0
        return FakeResponse()

    monkeypatch.setenv("IMOBHUNTER_SICAR_API_BASE_URL", "https://sicar.test/api-sicar-imovel/v1")
    monkeypatch.setenv("IMOBHUNTER_SICAR_API_TOKEN", "token")
    monkeypatch.setattr("imobhunter.sources.sicar.httpx.get", fake_get)

    result = SICARAdapter().search(SearchRequest(car_code="BA-176934-20170113-TEST"))

    assert len(result) == 1
    assert result[0].property_id == "BA-176934-20170113-TEST"
    assert result[0].area_m2 == 105000
    assert result[0].city == "Barreiras"


def test_sicar_api_status_requires_credentials(monkeypatch):
    monkeypatch.setenv("IMOBHUNTER_SICAR_API_BASE_URL", "https://sicar.test")
    monkeypatch.delenv("IMOBHUNTER_SICAR_API_TOKEN", raising=False)

    assert SICARAdapter().status().status == "not_configured"
