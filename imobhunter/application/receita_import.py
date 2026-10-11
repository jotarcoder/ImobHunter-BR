from __future__ import annotations

import csv
import sqlite3
import zipfile
from pathlib import Path
from collections.abc import Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS rf_companies (
    cnpj_base TEXT PRIMARY KEY,
    legal_name TEXT NOT NULL,
    legal_nature TEXT DEFAULT '',
    responsible_qualification TEXT DEFAULT '',
    share_capital REAL,
    company_size TEXT DEFAULT '',
    source_file TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS rf_establishments (
    cnpj TEXT PRIMARY KEY,
    cnpj_base TEXT NOT NULL,
    branch_type TEXT DEFAULT '',
    trade_name TEXT DEFAULT '',
    registration_status TEXT DEFAULT '',
    status_date TEXT DEFAULT '',
    start_date TEXT DEFAULT '',
    main_cnae TEXT DEFAULT '',
    secondary_cnae TEXT DEFAULT '',
    street_type TEXT DEFAULT '',
    street TEXT DEFAULT '',
    street_number TEXT DEFAULT '',
    complement TEXT DEFAULT '',
    neighborhood TEXT DEFAULT '',
    postal_code TEXT DEFAULT '',
    state TEXT DEFAULT '',
    municipality_code TEXT DEFAULT '',
    email TEXT DEFAULT '',
    source_file TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_rf_estab_city ON rf_establishments(state, municipality_code);
CREATE INDEX IF NOT EXISTS idx_rf_estab_cnae ON rf_establishments(main_cnae);
CREATE INDEX IF NOT EXISTS idx_rf_estab_base ON rf_establishments(cnpj_base);
"""


def _normalize_cnpj_base(value: str) -> str:
    return "".join(ch for ch in value.strip() if ch.isdigit()).zfill(8)


def _read_csv_member(archive: zipfile.ZipFile, member: str):
    # Receita Federal's public CNPJ archives use semicolon-separated,
    # headerless files commonly encoded as Latin-1.
    with archive.open(member) as binary:
        import io
        text = io.TextIOWrapper(binary, encoding="latin-1", newline="")
        yield from csv.reader(text, delimiter=";")


def _members(path: Path, kind: str) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return [n for n in archive.namelist()
                if not n.endswith("/") and kind in Path(n).name.upper()]


def import_receita_archives(database_path: str | Path, archive_paths: Iterable[str | Path],
                            batch_size: int = 2000) -> dict[str, int]:
    """Stream official Receita Federal CNPJ ZIP files into the local SQLite database.

    Accept ZIP archives whose member names include EMPRESAS and/or ESTABELECIMENTOS.
    Data is stored locally; this function makes no network requests and performs no geocoding.
    """
    db_path = Path(database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {"companies": 0, "establishments": 0}
    with sqlite3.connect(db_path) as db:
        db.executescript(SCHEMA)
        for raw_path in archive_paths:
            path = Path(raw_path)
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                for member in names:
                    if member.endswith("/"):
                        continue
                    basename = Path(member).name.upper()
                    if "EMPRESAS" in basename:
                        batch = []
                        for row in _read_csv_member(archive, member):
                            if len(row) < 7:
                                continue
                            base = _normalize_cnpj_base(row[0])
                            if not base or not row[1].strip():
                                continue
                            try:
                                capital = float(row[4].replace(",", "."))
                            except (ValueError, IndexError):
                                capital = None
                            batch.append((base, row[1].strip(), row[2].strip(), row[3].strip(),
                                          capital, row[5].strip(), path.name))
                            if len(batch) >= batch_size:
                                db.executemany("""INSERT INTO rf_companies
                                    (cnpj_base,legal_name,legal_nature,responsible_qualification,
                                     share_capital,company_size,source_file)
                                    VALUES (?,?,?,?,?,?,?)
                                    ON CONFLICT(cnpj_base) DO UPDATE SET
                                    legal_name=excluded.legal_name, legal_nature=excluded.legal_nature,
                                    responsible_qualification=excluded.responsible_qualification,
                                    share_capital=excluded.share_capital, company_size=excluded.company_size,
                                    source_file=excluded.source_file""", batch)
                                counts["companies"] += len(batch)
                                batch.clear()
                        if batch:
                            db.executemany("""INSERT INTO rf_companies
                                (cnpj_base,legal_name,legal_nature,responsible_qualification,
                                 share_capital,company_size,source_file)
                                VALUES (?,?,?,?,?,?,?)
                                ON CONFLICT(cnpj_base) DO UPDATE SET
                                legal_name=excluded.legal_name, legal_nature=excluded.legal_nature,
                                responsible_qualification=excluded.responsible_qualification,
                                share_capital=excluded.share_capital, company_size=excluded.company_size,
                                source_file=excluded.source_file""", batch)
                            counts["companies"] += len(batch)
                    elif "ESTABELECIMENTOS" in basename:
                        batch = []
                        for row in _read_csv_member(archive, member):
                            if len(row) < 30:
                                continue
                            base = _normalize_cnpj_base(row[0])
                            cnpj = base + row[1].strip().zfill(4) + row[2].strip().zfill(2)
                            if len(cnpj) != 14:
                                continue
                            batch.append((
                                cnpj, base, row[3].strip(), row[4].strip(), row[5].strip(),
                                row[6].strip(), row[10].strip(), row[11].strip(), row[12].strip(),
                                row[13].strip(), row[14].strip(), row[15].strip(), row[16].strip(),
                                row[17].strip(), row[18].strip(), row[19].strip(), row[20].strip(),
                                row[27].strip() if len(row) > 27 else "", path.name
                            ))
                            if len(batch) >= batch_size:
                                db.executemany("""INSERT INTO rf_establishments
                                    (cnpj,cnpj_base,branch_type,trade_name,registration_status,status_date,
                                     start_date,main_cnae,secondary_cnae,street_type,street,street_number,
                                     complement,neighborhood,postal_code,state,municipality_code,email,source_file)
                                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                    ON CONFLICT(cnpj) DO UPDATE SET
                                    trade_name=excluded.trade_name, registration_status=excluded.registration_status,
                                    main_cnae=excluded.main_cnae, secondary_cnae=excluded.secondary_cnae,
                                    street=excluded.street, street_number=excluded.street_number,
                                    complement=excluded.complement, neighborhood=excluded.neighborhood,
                                    postal_code=excluded.postal_code, state=excluded.state,
                                    municipality_code=excluded.municipality_code, source_file=excluded.source_file""", batch)
                                counts["establishments"] += len(batch)
                                batch.clear()
                        if batch:
                            db.executemany("""INSERT INTO rf_establishments
                                (cnpj,cnpj_base,branch_type,trade_name,registration_status,status_date,
                                 start_date,main_cnae,secondary_cnae,street_type,street,street_number,
                                 complement,neighborhood,postal_code,state,municipality_code,email,source_file)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                ON CONFLICT(cnpj) DO UPDATE SET
                                trade_name=excluded.trade_name, registration_status=excluded.registration_status,
                                main_cnae=excluded.main_cnae, secondary_cnae=excluded.secondary_cnae,
                                street=excluded.street, street_number=excluded.street_number,
                                complement=excluded.complement, neighborhood=excluded.neighborhood,
                                postal_code=excluded.postal_code, state=excluded.state,
                                municipality_code=excluded.municipality_code, source_file=excluded.source_file""", batch)
                            counts["establishments"] += len(batch)
    return counts



def search_receita_establishments(database_path: str | Path, query: str = "",
                                  state: str = "", cnae_prefix: str = "",
                                  limit: int = 500) -> list[dict[str, object]]:
    """Search locally imported CNPJ records by name, CNPJ, UF and primary CNAE."""
    limit = max(1, min(int(limit), 5000))
    db_path = Path(database_path)
    if not db_path.exists():
        return []
    clauses = []
    params: list[object] = []
    if query.strip():
        term = "%" + query.strip().replace("%", "\\%").replace("_", "\\_") + "%"
        clauses.append("(c.legal_name LIKE ? ESCAPE '\\\\' OR e.trade_name LIKE ? ESCAPE '\\\\' OR e.cnpj LIKE ?)")
        params.extend([term, term, term])
    if state.strip():
        clauses.append("e.state = ?")
        params.append(state.strip().upper())
    if cnae_prefix.strip():
        clauses.append("e.main_cnae LIKE ?")
        params.append(cnae_prefix.strip() + "%")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        try:
            rows = db.execute(
                "SELECT e.cnpj, c.legal_name, e.trade_name, e.registration_status, "
                "e.main_cnae, e.street_type, e.street, e.street_number, e.complement, "
                "e.neighborhood, e.postal_code, e.state, e.municipality_code, e.email, "
                "c.company_size, c.share_capital, e.source_file "
                "FROM rf_establishments e LEFT JOIN rf_companies c ON c.cnpj_base=e.cnpj_base"
                + where + " ORDER BY c.legal_name, e.cnpj LIMIT ?",
                [*params, limit],
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [dict(row) for row in rows]
