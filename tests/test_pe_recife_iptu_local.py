"""Offline regression tests for Recife 2025/2026 public property CSVs."""
import csv

import pytest

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.pe_recife_iptu_local import RecifeIPTULocalStore


HEADERS = [
    "Número do contribuinte", "CPF/CNPJ mascarado do contribuinte", "ano do exercício",
    "logradouro", "numero", "complemento", "bairro", "cidade", "estado",
    "AREA TERRENO", "AREA CONSTRUIDA", "latitude", "longitude", "tipo de uso do imóvel",
]


def write_csv(path, year, *, city="RECIFE", street="AV NORTE", n="10"):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=HEADERS, delimiter=";")
        writer.writeheader()
        for complement in ("APTO 1", "APTO 2"):
            writer.writerow({
                "Número do contribuinte": "PRIVATE_TAXPAYER_ID",
                "CPF/CNPJ mascarado do contribuinte": "PRIVATE_DOC",
                "ano do exercício": str(year), "logradouro": street,
                "numero": n, "complemento": complement, "bairro": "Centro",
                "cidade": city, "estado": "PE", "AREA TERRENO": "250,5",
                "AREA CONSTRUIDA": "90,5", "latitude": "-8,0339", "longitude": "-34,8964",
                "tipo de uso do imóvel": "RESIDENCIAL",
            })
    return path


def test_import_2025_2026_is_atomic_privacy_safe_and_prefers_newest(tmp_path):
    paths = [write_csv(tmp_path / f"iptu-{year}.csv", year) for year in (2025, 2026)]
    store = RecifeIPTULocalStore(tmp_path / "private-index")
    assert store.import_files(paths) == {2025: 2, 2026: 2}
    reopened = RecifeIPTULocalStore(tmp_path / "private-index")
    assert reopened.counts() == {2025: 2, 2026: 2}
    rows, diag = reopened.search(SearchRequest(address="Avenida Norte", number="10", city="Recife", state="PE"))
    assert len(rows) == 2 and diag["fiscal_year"] == 2026
    assert diag["matching_units"] == 2
    assert rows[0].area_m2 == 250.5
    assert rows[0].latitude == -8.0339
    assert rows[0].attributes["area_construida_m2"] == 90.5
    assert rows[0].attributes["sql"] is None
    assert rows[0].attributes["iptu_registration_number"] is None
    assert "PRIVATE" not in str(rows)
    raw_db = store.database.read_bytes()
    assert b"PRIVATE_TAXPAYER_ID" not in raw_db
    assert b"PRIVATE_DOC" not in raw_db


def test_wrong_city_or_corrupt_reimport_preserves_prior_database(tmp_path):
    path = write_csv(tmp_path / "valid.csv", 2026)
    store = RecifeIPTULocalStore(tmp_path / "index")
    store.import_files([path])
    wrong = write_csv(tmp_path / "other.csv", 2025, city="SALVADOR")
    with pytest.raises(ValueError, match="município diferente"):
        store.import_files([wrong])
    assert store.counts() == {2026: 2}
    with pytest.raises(ValueError, match="dois arquivos do mesmo"):
        store.import_files([path, write_csv(tmp_path / "valid-copy.csv", 2026)])
    assert store.counts() == {2026: 2}


def test_no_address_or_wrong_street_cannot_invent_sql(tmp_path):
    path = write_csv(tmp_path / "valid.csv", 2026)
    store = RecifeIPTULocalStore(tmp_path / "index")
    store.import_files([path])
    for street, num in (("Rua Inexistente", "10"), ("Avenida Norte", "99"), ("Avenida Norte", "10-A")):
        records, _ = store.search(SearchRequest(address=street, number=num, city="Recife", state="PE"))
        assert not records


def test_real_adapter_prefers_local_index_without_any_network(tmp_path):
    import httpx
    from imobhunter.sources.official_municipal_services import OfficialMunicipalServicesAdapter

    path = write_csv(tmp_path / "recife-2026.csv", 2026)
    store = RecifeIPTULocalStore(tmp_path / "local-index")
    store.import_files([path])
    def forbid_network(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("CSV local não deve acessar API externa")

    with httpx.Client(transport=httpx.MockTransport(forbid_network)) as client:
        adapter = OfficialMunicipalServicesAdapter(
            cache_dir=tmp_path / "cache", client=client, recife_store=store,
        )
        results = adapter.search(SearchRequest(
            address="Avenida Norte", number="10", city="Recife", state="PE",
        ))
        assert len(results) == 2
        assert results[0].attributes["source"] == adapter.source_id
        assert results[0].attributes["iptu_registration_number"] is None
        assert adapter.last_diagnostics["Recife"]["local_csv"]["fiscal_year"] == 2026
