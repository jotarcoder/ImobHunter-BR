"""Import municipal IPTU 2025 Parquet through the same local-source workflow."""
from __future__ import annotations

import sqlite3

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from imobhunter.application.custom_municipal_sources import CustomMunicipalStore
from imobhunter.domain.models import SearchRequest
from imobhunter.sources.custom_municipal import CustomMunicipalAdapter


def _sample_parquet(tmp_path):
    # The double suffix is intentional: municipality exports sometimes arrive
    # as "iptu_2025.parquet.parquet" from download portals.
    path = tmp_path / "iptu_2025.parquet.parquet"
    table = pa.table({
        "NUMERO DO CONTRIBUINTE": ["001.123.0045-9", "001.123.0046-0"],
        "NOME DE LOGRADOURO DO IMOVEL": ["RUA DO TESTE", "RUA DO TESTE"],
        "NUMERO DO IMOVEL": ["100", "102"],
        "AREA DO TERRENO": [125, 220],
        "AREA CONSTRUIDA": [100, 180],
        "ANO DO EXERCICIO": [2025, 2025],
    })
    pq.write_table(table, path)
    return path


def test_sp_custom_municipal_parquet_imports_indexed_locally(tmp_path, monkeypatch):
    store = CustomMunicipalStore(tmp_path / "municipal")
    source = store.add("IPTU SP 2025", "São Paulo", "SP")
    original = _sample_parquet(tmp_path)
    original_data = original.read_bytes()
    progress = []
    imported, count = store.import_file(
        source.source_id, original, progress=progress.append,
    )
    assert count == 2
    assert progress and progress[-1] == count
    assert imported.file_name == source.id + ".sqlite3"
    database = store.local_path(imported)
    assert database and database.exists()
    assert original.read_bytes() == original_data
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM iptu_sp").fetchone()[0] == 2

    # Search must use the SQLite index, not load the full Parquet to memory.
    def reject_scan(*_a, **_kw):
        raise AssertionError("Full file scan should never occur")

    monkeypatch.setattr("imobhunter.sources.custom_municipal.read_municipal_file", reject_scan)
    restored = CustomMunicipalStore(store.directory).get(source.source_id)
    assert restored is not None
    adapter = CustomMunicipalAdapter(restored, CustomMunicipalStore(store.directory))
    result = adapter.search(
        SearchRequest(address="Rua do Teste", number="100", city="São Paulo", state="SP")
    )
    assert len(result) == 1
    assert result[0].attributes["sql"] == "001.123.0045-9"
    assert result[0].block == "123"
    assert result[0].lot == "0045"
    assert result[0].area_m2 == 125
    assert result[0].provenance[0].source_id == source.source_id
    assert not adapter.search(SearchRequest(
        address="Rua do Teste", number="100", city="Santos", state="SP"
    ))
    assert store.remove(source.source_id)
    assert not database.exists()
    assert original.is_file()


def test_parquet_other_municipality_rejected_without_wrong_attribution(tmp_path):
    store = CustomMunicipalStore(tmp_path / "municipal")
    source = store.add("IPTU", "Santos", "SP")
    path = _sample_parquet(tmp_path)
    with pytest.raises(ValueError, match="São Paulo/SP"):
        store.import_file(source.source_id, path)
    assert store.get(source.source_id).file_name == ""
    assert path.exists()


def test_bad_parquet_keeps_previous_valid_municipal_file(tmp_path):
    store = CustomMunicipalStore(tmp_path / "municipal")
    source = store.add("IPTU", "São Paulo", "SP")
    old = tmp_path / "municipal.csv"
    old.write_text("logradouro;numero;sql\nRua Antiga;1;00123\n", encoding="utf-8")
    previous, _ = store.import_file(source.source_id, old)
    old_copy = store.local_path(previous)
    bad = tmp_path / "corrupted.parquet"
    bad.write_text("not a parquet", encoding="utf-8")
    with pytest.raises(ValueError, match="Parquet"):
        store.import_file(source.source_id, bad)
    restored = store.get(source.source_id)
    assert restored is not None and restored.file_name == previous.file_name
    assert old_copy and old_copy.is_file()


def test_create_source_dialog_exposes_local_upload_and_background_processing():
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / "imobhunter" / "ui_settings.py").read_text(
        encoding="utf-8"
    )
    assert 'form.addRow("Arquivo municipal", file_row)' in script
    assert "class CustomMunicipalImportWorker(QRunnable)" in script
    assert 'def _custom_import_finished(self, source_id: str, result: dict)' in script
    assert "QThreadPool.globalInstance().start(worker)" in script
