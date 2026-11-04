"""CNPJ/telephone enrichment is source-grounded, local and backwards compatible."""
from __future__ import annotations

import csv
import sqlite3
import zipfile
from pathlib import Path

from imobhunter.application.market_export import export_market_results
from imobhunter.application.market_intelligence import MarketIntelligenceStore
from imobhunter.application.osm_business_search import fetch_osm_businesses
from imobhunter.application.receita_import import (
    import_receita_archives,
    search_receita_establishments,
)


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"elements": [
            {"type": "node", "id": 12, "lat": -23.55, "lon": -46.63,
             "tags": {"name": "Loja com CNPJ", "shop": "clothes", "ref:cnpj": "12.345.678/0001-99",
                      "contact:phone": "+55 11 4000-1111"}},
            {"type": "node", "id": 13, "lat": -23.5502, "lon": -46.6302,
             "tags": {"name": "Loja sem CNPJ", "shop": "clothes", "phone": "11 4000-2222"}},
        ]}


class FakeClient:
    def post(self, url, data):
        return FakeResponse()


def _official_zip(tmp_path: Path, phone: str = "987654321") -> Path:
    path = tmp_path / "estabelecimentos.zip"
    fields = [""] * 30
    fields[0:3] = ["12345678", "0001", "99"]
    fields[4] = "Loja com CNPJ"
    fields[11] = "4711301"
    fields[13:16] = ["R", "Rua A", "10"]
    fields[17:21] = ["Centro", "01000000", "SP", "7107"]
    fields[21] = "11"
    fields[22] = phone
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ESTABELECIMENTOS.CSV", ";".join(fields) + "\n")
    return path


def test_osm_tags_are_explicit_not_inferred_from_business_names(tmp_path: Path):
    points = fetch_osm_businesses(-23.55, -46.63, 1, client=FakeClient())
    assert points[0]["cnpj"] == "12345678000199"
    assert points[0]["phone"] == "+55 11 4000-1111"
    assert points[1]["cnpj"] == ""
    assert points[1]["phone"] == "11 4000-2222"

    store = MarketIntelligenceStore(tmp_path / "market.sqlite3")
    assert store.import_osm_businesses(points) == 2
    assert store.import_osm_businesses(points) == 0
    results = store.search_radius(-23.55, -46.63, 1)
    assert len(results) == 2
    assert results[0]["phone"] == "+55 11 4000-1111"
    assert results[1]["phone"] == "11 4000-2222"
    assert results[1]["cnpj"] == ""


def test_old_local_sqlite_rows_survive_phone_migration(tmp_path: Path):
    db_path = tmp_path / "old.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute("""CREATE TABLE businesses (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, cnpj TEXT DEFAULT '',
            cnae TEXT DEFAULT '', address TEXT DEFAULT '', city TEXT DEFAULT '',
            state TEXT DEFAULT '', latitude REAL, longitude REAL,
            revenue_reported REAL, revenue_period TEXT DEFAULT '',
            revenue_estimate REAL, estimate_method TEXT DEFAULT '',
            source TEXT DEFAULT '', updated_at TEXT DEFAULT ''
        )""")
        db.execute(
            "INSERT INTO businesses(name,latitude,longitude,source) VALUES (?,?,?,?)",
            ("Empresa antiga", -23.55, -46.63, "Importação antiga"),
        )
    store = MarketIntelligenceStore(db_path)
    assert store.count() == 1
    results = store.search_radius(-23.55, -46.63, 1)
    assert len(results) == 1
    assert results[0]["name"] == "Empresa antiga"
    assert results[0]["phone"] == ""


def test_receita_phone_resolves_only_exact_cnpj_and_exports(tmp_path: Path):
    db_path = tmp_path / "market.sqlite3"
    store = MarketIntelligenceStore(db_path)
    csv_path = tmp_path / "geo.csv"
    csv_path.write_text(
        "name,cnpj,latitude,longitude,source\n"
        "Loja certa,12345678000199,-23.55,-46.63,Base local\n"
        "Loja com nome parecido,12345678000198,-23.5502,-46.6302,Base local\n",
        encoding="utf-8",
    )
    assert store.import_csv(csv_path) == 2
    official_zip = _official_zip(tmp_path)
    counts = import_receita_archives(db_path, [official_zip])
    assert counts["establishments"] == 1
    source_rows = search_receita_establishments(db_path, query="12345678000199")
    assert source_rows[0]["phone"] == "11987654321"
    rows = store.search_radius(-23.55, -46.63, 1)
    by_name = {row["name"]: row for row in rows}
    assert by_name["Loja certa"]["phone"] == "11987654321"
    assert by_name["Loja com nome parecido"]["phone"] == ""
    output = tmp_path / "export.csv"
    export_market_results(rows, output)
    with output.open(encoding="utf-8-sig", newline="") as handle:
        exported = {row["name"]: row for row in csv.DictReader(handle)}
    assert exported["Loja certa"]["phone"] == "11987654321"
    assert exported["Loja com nome parecido"]["phone"] == ""


def test_importer_upgrades_old_receita_schema_and_preserves_phone(tmp_path: Path):
    db_path = tmp_path / "old_receita.sqlite3"
    from imobhunter.application.receita_import import SCHEMA as RECEITA_SCHEMA
    old_schema = RECEITA_SCHEMA.replace("    phone TEXT DEFAULT '',\n", "")
    # Recreate the entire previous table definition, only without phone.
    assert old_schema != RECEITA_SCHEMA
    with sqlite3.connect(db_path) as db:
        db.executescript(old_schema)
    archive = _official_zip(tmp_path)
    assert import_receita_archives(db_path, [archive])["establishments"] == 1
    with sqlite3.connect(db_path) as db:
        assert db.execute(
            "SELECT phone FROM rf_establishments WHERE cnpj='12345678000199'"
        ).fetchone() == ("11987654321",)


def test_window_keeps_map_separate_and_shows_results_phone():
    ui = (Path(__file__).resolve().parents[1] / "imobhunter/ui_market.py").read_text(encoding="utf-8")
    dialog = ui.split("class MarketIntelligenceDialog", 1)[1].split("class ReceitaBrowseDialog", 1)[0]
    assert 'self.open_results_button = QPushButton("Ver resultados →")' in dialog
    assert "self.tabs.setCurrentWidget(self.results_scroll)" in dialog
    assert 'self.results_table = QTableWidget(0, 9)' in dialog
    assert '"Empresa", "CNPJ", "Telefone", "CNAE"' in dialog
    assert "self.table = QTableWidget" not in dialog
