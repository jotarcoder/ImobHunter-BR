"""Mogi: date-bound municipal data must never create fabricated current SQL."""
import httpx

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.official_municipal_services import OfficialMunicipalServicesAdapter
from imobhunter.sources.sp_mogi_cadastre import (
    MOGI_DATASET_API, mogi_historical_file_record,
)


def _request(number="100", street="Rua Doutor Deodato Wertheimer"):
    return SearchRequest(address=street, number=number, city="Mogi das Cruzes", state="SP")


def test_mogi_exact_historical_address_projection_drops_pii_and_money():
    row = {
        "logradouro": "RUA DOUTOR DEODATO WERTHEIMER", "nro_local": "0100",
        "cadastro_id": "0987654321", "area_terreno": "250,40",
        "proprietario": "SEGREDO", "cpf": "PRIVATE",
        "valor_venal": "999999", "debito_iptu": "123",
        "zona_fiscal": "Z2", "situcao": "2024",
    }
    record = mogi_historical_file_record(
        row, _request(), "mogi_local", "approved_2024.csv"
    )
    assert record is not None
    assert record.address.endswith(", 100")
    assert record.attributes["historical_cadastro_id"] == "0987654321"
    assert record.area_m2 == 250.4
    assert record.block is None and record.lot is None
    assert record.property_id is None
    assert record.attributes["sql"] is None
    assert record.attributes["iptu_registration_number"] is None
    assert record.attributes["cadastre_match"] == "exact_historical_address_only"
    assert record.attributes["source_year"] == 2024
    assert "SEGREDO" not in str(record.attributes)
    assert "999999" not in str(record.attributes)
    assert "PRIVATE" not in str(record.attributes)
    assert record.owner_name is None


def test_mogi_same_street_different_number_or_ambiguous_street_is_rejected():
    row = {"logradouro": "Rua Doutor Deodato Wertheimer",
           "nro_local": "100", "cadastro_id": "123"}
    assert mogi_historical_file_record(
        row, _request(number="102"), "s", "file.csv"
    ) is None
    assert mogi_historical_file_record(
        row, _request(street="Rua Doutor Deodato"), "s", "file.csv"
    ) is None
    assert mogi_historical_file_record(
        row, _request(number="100 OR 1=1"), "s", "file.csv"
    ) is None
    assert mogi_historical_file_record(
        {**row, "cadastro_id": None}, _request(), "s", "file.csv"
    ) is None


def test_mogi_official_ckan_only_gets_catalogue_metadata(tmp_path):
    requested = []
    def handler(req):
        requested.append(str(req.url))
        assert req.url.path.endswith("/api/3/action/package_show")
        assert req.url.params["id"] == "cadastro-imobiliario"
        return httpx.Response(200, json={
            "success": True,
            "result": {
                "title": "CADASTRO IMOBILIÁRIO", "license_id": "",
                "resources": [
                    {"name": "pmmc_imobiliario_2024_part1.csv", "format": "CSV"},
                    {"name": "iptu_itbi_2024.csv", "format": "CSV"},
                ],
            },
        })
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    results = adapter.search(_request())
    client.close()
    assert results == []
    assert len(requested) == 1
    assert MOGI_DATASET_API in requested[0]
    diag = adapter.last_diagnostics["Mogi das Cruzes"]
    assert diag["last_published_exercise"] == 2024
    assert diag["dataset_license"] == "not_specified"
    assert diag["available_cadastre_files"] == 1
    assert diag["registration_verified"] is False
    assert diag["automated_download"] is False
    assert "Mogi das Cruzes" in adapter.last_errors


def test_mogi_ckan_failure_is_not_confused_with_absent_imovel(tmp_path):
    def handler(_req):
        raise httpx.ConnectTimeout("CKAN indisponível")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    assert adapter.search(_request()) == []
    client.close()
    assert "ConnectTimeout" in adapter.last_errors["Mogi das Cruzes"]
