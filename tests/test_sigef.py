import json

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.sigef import SIGEFAdapter


def test_sigef_reads_json_and_converts_area(tmp_path):
    path = tmp_path / "sigef.json"
    path.write_text(json.dumps({"parcelas": [{
        "parcelaCodigo": "SIGEF-001",
        "municipio": "Campinas",
        "uf": "SP",
        "areaHectares": 3.5,
        "status": "CERTIFICADA",
        "registroMatricula": "12345",
        "titularNome": "Titular Teste",
        "titularCpf": "00000000000",
    }]}), encoding="utf-8")
    result = SIGEFAdapter(path).search(SearchRequest(city="Campinas", state="SP"))
    assert len(result) == 1
    assert result[0].property_id == "SIGEF-001"
    assert result[0].area_m2 == 35000
    assert result[0].registry_number == "12345"
    assert result[0].owner_name == "Titular Teste"
    assert result[0].attributes["status"] == "CERTIFICADA"


def test_sigef_reads_geojson(tmp_path):
    path = tmp_path / "sigef.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"parcelaCodigo": "SIGEF-002", "municipio": "Sorocaba", "uf": "SP", "areaHectares": 1.2},
            "geometry": {"type": "Polygon", "coordinates": []},
        }],
    }), encoding="utf-8")
    result = SIGEFAdapter(path).search(SearchRequest(city="Sorocaba", state="SP"))
    assert result[0].property_id == "SIGEF-002"
    assert result[0].area_m2 == 12000
    assert result[0].attributes["geometry"]["type"] == "Polygon"


def test_sigef_reads_csv(tmp_path):
    path = tmp_path / "sigef.csv"
    path.write_text("parcela_codigo,municipio,uf,area_hectares\nSIGEF-003,Campinas,SP,2.5\n", encoding="utf-8")
    result = SIGEFAdapter(path).search(SearchRequest(city="Campinas", state="SP"))
    assert result[0].area_m2 == 25000


def test_sigef_not_configured():
    adapter = SIGEFAdapter()
    assert adapter.status().status == "not_configured"
    assert adapter.search(SearchRequest(address="x")) == []
