from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pytest

from imobhunter.application.receita_geo import import_receita_coordinates
from imobhunter.application.receita_import import import_receita_archives
from imobhunter.application.market_intelligence import MarketIntelligenceStore


def test_receita_coordinate_join_enables_radius_search(tmp_path: Path):
    db_path = tmp_path / "market.sqlite3"
    archive_path = tmp_path / "cnpj.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "EMPRESAS.CSV",
            "12345678;EMPRESA EXEMPLO LTDA;2062;49;1000,00;03;\n",
        )
        fields = [""] * 30
        fields[0:3] = ["12345678", "0001", "99"]
        fields[3] = "1"
        fields[4] = "LOJA EXEMPLO"
        fields[5] = "02"
        fields[10] = "20200101"
        fields[11] = "4711301"
        fields[13] = "R"
        fields[14] = "RUA TESTE"
        fields[15] = "10"
        fields[17] = "CENTRO"
        fields[18] = "01000000"
        fields[19] = "SP"
        fields[20] = "7107"
        archive.writestr("ESTABELECIMENTOS.CSV", ";".join(fields) + "\n")
    import_receita_archives(db_path, [archive_path])

    csv_path = tmp_path / "coords.csv"
    csv_path.write_text(
        "cnpj,latitude,longitude,source\n"
        "12345678000199,-23.55,-46.63,coordenadas de teste\n",
        encoding="utf-8",
    )
    result = import_receita_coordinates(db_path, csv_path)
    assert result == {"matched": 1, "inserted": 1, "updated": 0, "skipped": 0}
    store = MarketIntelligenceStore(db_path)
    found = store.search_radius(-23.55, -46.63, 1)
    assert len(found) == 1
    assert found[0]["cnpj"] == "12345678000199"
    assert found[0]["name"] == "LOJA EXEMPLO"

    # Re-importing the same coordinate file refreshes the existing CNPJ row,
    # instead of creating a second business record.
    result_again = import_receita_coordinates(db_path, csv_path)
    assert result_again == {"matched": 1, "inserted": 0, "updated": 1, "skipped": 0}
    assert store.count() == 1
    assert len(store.search_radius(-23.55, -46.63, 1)) == 1


def test_coordinate_import_skips_unknown_and_invalid_coordinates(tmp_path: Path):
    db_path = tmp_path / "market.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE rf_establishments (cnpj TEXT PRIMARY KEY, cnpj_base TEXT)")
        db.execute("CREATE TABLE rf_companies (cnpj_base TEXT PRIMARY KEY, legal_name TEXT)")
        db.execute(
            "CREATE TABLE businesses (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
            "cnpj TEXT DEFAULT '', cnae TEXT DEFAULT '', address TEXT DEFAULT '', "
            "city TEXT DEFAULT '', state TEXT DEFAULT '', latitude REAL, longitude REAL, "
            "revenue_reported REAL, revenue_period TEXT DEFAULT '', revenue_estimate REAL, "
            "estimate_method TEXT DEFAULT '', source TEXT DEFAULT '', updated_at TEXT DEFAULT '')"
        )
    csv_path = tmp_path / "coords.csv"
    csv_path.write_text(
        "cnpj,latitude,longitude\n"
        "00000000000000,0,0\n"
        "12345678000199,91,0\n"
        "12345678000199,not-a-number,0\n",
        encoding="utf-8",
    )
    result = import_receita_coordinates(db_path, csv_path)
    assert result == {"matched": 0, "inserted": 0, "updated": 0, "skipped": 3}


def test_coordinate_import_requires_receita_tables(tmp_path: Path):
    db_path = tmp_path / "empty.sqlite3"
    db_path.touch()
    csv_path = tmp_path / "coords.csv"
    csv_path.write_text("cnpj,latitude,longitude\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Importe primeiro"):
        import_receita_coordinates(db_path, csv_path)


def test_radius_search_excludes_registered_businesses_without_coordinates(tmp_path: Path):
    store = MarketIntelligenceStore(tmp_path / "market.sqlite3")
    csv_path = tmp_path / "companies.csv"
    csv_path.write_text(
        "name,cnpj,cnae,latitude,longitude\\n"
        "Geolocalizada,123,4711301,-23.55,-46.63\\n"
        "Sem coordenadas,456,4711301,,\\n",
        encoding="utf-8",
    )
    assert store.import_csv(csv_path) == 1
    # Receita registrations can exist locally before any coordinates are linked.
    import sqlite3
    with sqlite3.connect(store.path) as db:
        db.execute(
            "INSERT INTO businesses (name, cnpj, cnae) VALUES (?, ?, ?)",
            ("Sem coordenadas", "456", "4711301"),
        )
    assert store.count() == 2
    found = store.search_radius(-23.55, -46.63, 2)
    assert [item["name"] for item in found] == ["Geolocalizada"]
