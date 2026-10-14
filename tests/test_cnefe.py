import gzip
import io
import json
import zipfile


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
        "NM_LOGR;NUMERO;NM_MUNICIPIO;SIGLA_UF;COD_UNICO;QUADRA;LATITUDE;LONGITUDE\n"
        "PAMPLONA;1578;SAO PAULO;SP;456;9;-23.5601;-46.6601\n",
        encoding="utf-8",
    )

    records = CNEFEAdapter(path).search(
        SearchRequest(address="Rua Pamplona", number="1578", city="São Paulo", state="SP")
    )

    assert len(records) == 1
    assert records[0].property_id == "456"
    assert records[0].block == "9"


def test_cnefe_matches_street_type_prefix_and_address_only_search(tmp_path) -> None:
    path = tmp_path / "cnefe.csv"
    path.write_text(
        "NM_LOGR;NUMERO;NM_MUNICIPIO;SIGLA_UF;COD_UNICO;QUADRA\n"
        "R PAMPLONA;1578;SAO PAULO;SP;789;12\n"
        "R PAMPLONA;1600;SAO PAULO;SP;790;13\n",
        encoding="utf-8",
    )

    records = CNEFEAdapter(path).search(
        SearchRequest(address="Rua Pamplona", city="São Paulo", state="SP")
    )

    assert len(records) == 2
    assert {record.property_id for record in records} == {"789", "790"}


def test_cnefe_reports_missing_local_file(tmp_path) -> None:
    status = CNEFEAdapter(tmp_path / "missing.geojson").status()

    assert status.status == "error"
    assert "not found" in (status.message or "")


def test_cnefe_uses_official_remote_when_path_is_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("IMOBHUNTER_CNEFE_PATH", raising=False)

    status = CNEFEAdapter().status()

    assert status.status == "available"
    assert "IBGE" in (status.message or "")


def test_cnefe_zip_search(tmp_path) -> None:
    path = tmp_path / "cnefe.zip"
    csv_content = (
        "NM_LOGR;NUMERO;NM_MUNICIPIO;SIGLA_UF;COD_UNICO;QUADRA;LATITUDE;LONGITUDE\n"
        "PAMPLONA;1578;SAO PAULO;SP;789;12;-23.5602;-46.6602\n"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("3550308_SAO_PAULO.csv", csv_content)

    records = CNEFEAdapter(path).search(
        SearchRequest(address="Rua Pamplona", number="1578", city="São Paulo", state="SP")
    )

    assert len(records) == 1
    assert records[0].property_id == "789"
    assert records[0].block == "12"


def test_cnefe_remote_resolves_municipality_and_uses_cache(tmp_path, monkeypatch) -> None:
    from imobhunter.sources import cnefe

    source_zip = tmp_path / "3550308_SAO_PAULO.zip"
    csv_content = (
        "NM_LOGR;NUMERO;NM_MUNICIPIO;SIGLA_UF;COD_UNICO;QUADRA\n"
        "PAMPLONA;1578;SAO PAULO;SP;999;77\n"
    )
    with zipfile.ZipFile(source_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("3550308_SAO_PAULO.csv", csv_content)

    calls = {"catalog": 0}

    def fake_catalog(_url):
        calls["catalog"] += 1
        return [{
            "id": 3550308,
            "nome": "São Paulo",
            "microrregiao": {"mesorregiao": {"UF": {"sigla": "SP"}}},
        }]

    monkeypatch.setattr(cnefe, "_http_json", fake_catalog)
    monkeypatch.setattr(
        cnefe,
        "_http_text",
        lambda _url: '<a href="3550308_SAO_PAULO.zip">arquivo</a>',
    )
    monkeypatch.setattr(cnefe, "_download_remote_zip", lambda _url, _cache: source_zip)

    records = CNEFEAdapter(cache_dir=tmp_path / "cache").search(
        SearchRequest(address="Rua Pamplona", number="1578", city="São Paulo", state="SP")
    )

    assert len(records) == 1
    assert records[0].property_id == "999"
    assert records[0].block == "77"

    second = CNEFEAdapter(cache_dir=tmp_path / "cache").search(
        SearchRequest(address="Rua Pamplona", number="1578", city="São Paulo", state="SP")
    )
    assert len(second) == 1
    assert calls["catalog"] == 1
    assert (tmp_path / "cache" / "municipalities.json").is_file()



def test_http_text_decodes_gzip_compressed_response(monkeypatch) -> None:
    from imobhunter.sources import cnefe

    payload = gzip.compress(b'<a href="3550308_SAO_PAULO.zip">arquivo</a>')

    class FakeResponse:
        headers = {"Content-Encoding": "gzip"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return payload

    monkeypatch.setattr(cnefe, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    assert "3550308_SAO_PAULO.zip" in cnefe._http_text("https://ftp.ibge.gov.br/listing/")
