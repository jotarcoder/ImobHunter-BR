from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


def _digits(value: object) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def import_receita_coordinates(
    database_path: str | Path,
    coordinates_csv: str | Path,
) -> dict[str, int]:
    """Join locally imported Receita establishments to a coordinate CSV by full CNPJ.

    Required CSV columns: cnpj, latitude, longitude. Optional columns: source, updated_at.
    Only valid coordinates are accepted. No network requests or geocoding are performed.
    """
    db_path = Path(database_path)
    if not db_path.exists():
        raise ValueError("Importe primeiro os ZIPs oficiais do CNPJ.")
    with Path(coordinates_csv).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("O CSV de coordenadas está vazio ou sem cabeçalho.")
        fields = {field.strip().lower() for field in reader.fieldnames if field}
        if not {"cnpj", "latitude", "longitude"}.issubset(fields):
            raise ValueError("O CSV precisa conter cnpj, latitude e longitude.")
        records = list(reader)

    matched = inserted = updated = skipped = 0
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        db.execute("""
            CREATE TABLE IF NOT EXISTS businesses (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, cnpj TEXT DEFAULT '',
                cnae TEXT DEFAULT '', address TEXT DEFAULT '', city TEXT DEFAULT '',
                state TEXT DEFAULT '', latitude REAL, longitude REAL,
                revenue_reported REAL, revenue_period TEXT DEFAULT '',
                revenue_estimate REAL, estimate_method TEXT DEFAULT '',
                source TEXT DEFAULT '', updated_at TEXT DEFAULT ''
            )
        """)
        for raw in records:
            row = {(key or "").strip().lower(): (value or "").strip()
                   for key, value in raw.items()}
            cnpj = _digits(row.get("cnpj"))
            try:
                lat = float(row.get("latitude", "").replace(",", "."))
                lon = float(row.get("longitude", "").replace(",", "."))
            except ValueError:
                skipped += 1
                continue
            if len(cnpj) != 14 or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                skipped += 1
                continue
            establishment = db.execute("""
                SELECT e.*, c.legal_name FROM rf_establishments e
                LEFT JOIN rf_companies c ON c.cnpj_base=e.cnpj_base
                WHERE e.cnpj=?
            """, (cnpj,)).fetchone()
            if establishment is None:
                skipped += 1
                continue
            matched += 1
            address = " ".join(part for part in (
                establishment["street_type"], establishment["street"],
                establishment["street_number"], establishment["complement"],
                establishment["neighborhood"], establishment["postal_code"],
            ) if part)
            name = establishment["trade_name"] or establishment["legal_name"] or cnpj
            source = row.get("source") or "Receita Federal CNPJ + coordenadas CSV"
            existing = db.execute(
                "SELECT id FROM businesses WHERE cnpj=? ORDER BY id LIMIT 1", (cnpj,)
            ).fetchone()
            values = (
                name, establishment["main_cnae"], address, establishment["state"],
                lat, lon, source, row.get("updated_at", ""),
            )
            if existing:
                db.execute("""
                    UPDATE businesses SET name=?, cnae=?, address=?, state=?,
                    latitude=?, longitude=?, source=?, updated_at=? WHERE id=?
                """, (*values, existing["id"]))
                updated += 1
            else:
                db.execute("""
                    INSERT INTO businesses
                    (name,cnpj,cnae,address,state,latitude,longitude,source,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (name, cnpj, *values))
                inserted += 1
    return {"matched": matched, "inserted": inserted, "updated": updated, "skipped": skipped}
