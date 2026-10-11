from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pytest

from imobhunter.application.market_intelligence import MarketIntelligenceStore
from imobhunter.application.receita_geo import save_geocoded_establishment
from imobhunter.application.receita_import import import_receita_archives


def _database(tmp_path: Path) -> Path:
    db_path = tmp_path / "market.sqlite3"
    archive_path = tmp_path / "cnpj.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("EMPRESAS.CSV", "12345678;EMPRESA EXEMPLO LTDA;2062;49;1000,00;03;\n")
        fields = [""] * 30
        fields[0:3] = ["12345678", "0001", "99"]
        fields[4] = "LOJA EXEMPLO"
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
    return db_path


def test_save_geocoded_establishment_enables_radius_search(tmp_path: Path):
    db_path = _database(tmp_path)
    saved = save_geocoded_establishment(db_path, "12.345.678/0001-99", {
        "latitude": -23.55, "longitude": -46.63,
        "provider": "OpenStreetMap Nominatim",
        "attribution": "© OpenStreetMap contributors",
    })
    assert saved["cnpj"] == "12345678000199"
    found = MarketIntelligenceStore(db_path).search_radius(-23.55, -46.63, 1)
    assert len(found) == 1
    assert found[0]["cnpj"] == "12345678000199"
    assert found[0]["cnae"] == "4711301"


def test_same_cnpj_updates_existing_record(tmp_path: Path):
    db_path = _database(tmp_path)
    save_geocoded_establishment(db_path, "12345678000199", {"latitude": -23.55, "longitude": -46.63})
    save_geocoded_establishment(db_path, "12345678000199", {"latitude": -23.56, "longitude": -46.64})
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM businesses WHERE cnpj='12345678000199'").fetchone()[0] == 1
        assert db.execute("SELECT latitude,longitude FROM businesses WHERE cnpj='12345678000199'").fetchone() == (-23.56, -46.64)


@pytest.mark.parametrize("cnpj,result", [
    ("123", {"latitude": 0, "longitude": 0}),
    ("12345678000199", {"latitude": 91, "longitude": 0}),
    ("12345678000199", {"latitude": float("nan"), "longitude": 0}),
    ("12345678000199", {}),
])
def test_rejects_invalid_cnpj_or_coordinates(tmp_path: Path, cnpj: str, result: dict):
    db_path = _database(tmp_path)
    with pytest.raises(ValueError):
        save_geocoded_establishment(db_path, cnpj, result)
