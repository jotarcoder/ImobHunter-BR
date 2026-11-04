"""São Paulo IPTU Parquet: schema, SQLite indexes, provenance, offline search."""
from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from imobhunter.application.sp_iptu_parquet import (
    import_sp_iptu_parquet,
    search_sp_iptu_sqlite,
)
from imobhunter.domain.models import SearchRequest
from imobhunter.sources.municipal_iptu import MunicipalIPTUAdapter


def _sample(tmp_path: Path) -> Path:
    rows = [
        {
            "SQL": "123.456.0001-2", "NOME DE LOGRADOURO DO IMOVEL": "RUA SÃO JOÃO",
            "NUMERO DO IMOVEL": "100", "COMPLEMENTO DO IMOVEL": "SALA 1",
            "BAIRRO DO IMOVEL": "CENTRO", "CEP DO IMOVEL": "01001000",
            "AREA DO TERRENO": 145, "AREA CONSTRUIDA": 83,
            "ANO DO EXERCICIO": 2025,
        },
        {
            "SQL": "123.456.0002-3", "NOME DE LOGRADOURO DO IMOVEL": "RUA SÃO JOÃO",
            "NUMERO DO IMOVEL": "102", "COMPLEMENTO DO IMOVEL": "SALA 2",
            "BAIRRO DO IMOVEL": "CENTRO", "CEP DO IMOVEL": "01001000",
            "AREA DO TERRENO": 165, "AREA CONSTRUIDA": 95,
            "ANO DO EXERCICIO": 2025,
        },
        {
            "SQL": "123.456.0001-4", "NOME DE LOGRADOURO DO IMOVEL": "RUA SÃO JOÃO",
            "NUMERO DO IMOVEL": "100", "COMPLEMENTO DO IMOVEL": "SALA 3",
            "BAIRRO DO IMOVEL": "CENTRO", "CEP DO IMOVEL": "01001000",
            "AREA DO TERRENO": 145, "AREA CONSTRUIDA": 74,
            "ANO DO EXERCICIO": 2025,
        },
    ]
    file = tmp_path / "iptu_2025.parquet"
    pq.write_table(pa.Table.from_pylist(rows), file, row_group_size=2)
    return file


def test_import_and_search_by_exact_address_in_sp(tmp_path: Path):
    source = _sample(tmp_path)
    original = source.read_bytes()
    indexed, count = import_sp_iptu_parquet(source, tmp_path / "iptu_sp.sqlite3")
    assert indexed.is_file() and source.read_bytes() == original
    assert count == 3
    with sqlite3.connect(indexed) as db:
        indexes = {item[1] for item in db.execute("PRAGMA index_list(iptu_sp)")}
        assert "idx_iptu_sp_address" in indexes
        assert "idx_iptu_sp_sql" in indexes
        assert db.execute("SELECT value FROM metadata WHERE key='source_file'").fetchone()[0] == source.name
    adapter = MunicipalIPTUAdapter(indexed)
    records = adapter.search(SearchRequest(address="R. São João", number="100", city="São Paulo", state="SP"))
    assert len(records) == 2
    assert {x.property_id for x in records} == {"123.456.0001-2", "123.456.0001-4"}
    assert {x.lot for x in records} == {"0001"}
    assert records[0].block == "456"
    assert records[0].area_m2 == 145
    assert records[0].attributes["building_area_m2"] in (83, 74)
    assert records[0].attributes["iptu_reference_year"] == 2025
    assert records[0].attributes["iptu_current_debt_status"] == "not_verified"
    assert records[0].owner_name is None


def test_no_wrong_city_or_neighbour_number_matches(tmp_path: Path):
    source = _sample(tmp_path)
    indexed, count = import_sp_iptu_parquet(source, tmp_path / "iptu.sqlite3")
    assert count == 3
    wrong_city = SearchRequest(address="Rua São João", number="100", city="Santos", state="SP")
    assert not search_sp_iptu_sqlite(indexed, wrong_city)
    wrong_state = SearchRequest(address="Rua São João", number="100", city="São Paulo", state="RJ")
    assert not search_sp_iptu_sqlite(indexed, wrong_state)
    assert not search_sp_iptu_sqlite(indexed, SearchRequest(
        address="Rua São João", number="101", city="São Paulo", state="SP"
    ))
    assert not search_sp_iptu_sqlite(indexed, SearchRequest(address="Rua São João", city="São Paulo"))
    lots = search_sp_iptu_sqlite(indexed, SearchRequest(block="456", lot="1", city="São Paulo", state="SP"))
    assert len(lots) == 2


def test_failed_parquet_does_not_replace_existing_index(tmp_path: Path):
    source = _sample(tmp_path)
    dest = tmp_path / "index.sqlite3"
    assert import_sp_iptu_parquet(source, dest)[1] == 3
    bad = tmp_path / "other.parquet"
    pq.write_table(pa.table({"wrong": ["no sql"]}), bad)
    with pytest.raises(ValueError, match="colunas obrigatórias"):
        import_sp_iptu_parquet(bad, dest)
    assert len(search_sp_iptu_sqlite(dest, SearchRequest(
        address="Rua São João", number="100", city="São Paulo", state="SP"
    ))) == 2


def test_parquet_not_treated_as_json_and_non_parquet_rejected(tmp_path: Path):
    source = _sample(tmp_path)
    adapter = MunicipalIPTUAdapter(source)
    with pytest.raises(ValueError, match="Importe o Parquet"):
        adapter.search(SearchRequest(address="Rua São João", number="100"))
    corrupt = tmp_path / "bad.parquet"
    corrupt.write_text("isto não é parquet", encoding="utf-8")
    with pytest.raises(ValueError, match="Parquet válido"):
        import_sp_iptu_parquet(corrupt, tmp_path / "index.sqlite3")


def test_settings_dialog_exposes_parquet_and_starts_import_worker():
    ui = (Path(__file__).resolve().parents[1] / "imobhunter/ui_settings.py").read_text()
    assert '"IPTU municipal", "data_path", "CSV, JSON ou Parquet"' in ui
    assert "Dados IPTU (*.csv *.json *.parquet)" in ui
    assert "class SPIPTUImportWorker(QRunnable)" in ui
    assert "QThreadPool.globalInstance().start(worker)" in ui
    assert "sources/municipal_iptu/path" in ui
