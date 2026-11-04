"""Local-only index of Recife's public annual IPTU CSV *property attributes*.

Do not ingest taxpayer IDs, masked CPF/CNPJ, taxable values or amounts due.
The published taxpayer number is not a proven property inscription.
"""
from __future__ import annotations

import csv
import math
import os
import re
import sqlite3
import tempfile
import unicodedata
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest

SOURCE_URL = "https://dados.recife.pe.gov.br/dataset/imposto-predial-e-territorial-urbano-iptu"
MAX_FILE_BYTES = 300 * 1024 * 1024
MAX_ROWS_PER_FILE = 1_000_000
MAX_RESULTS = 30
REQUIRED = {"ano do exercício", "logradouro", "numero", "AREA TERRENO", "AREA CONSTRUIDA", "cidade", "estado"}
SCHEMA = """
CREATE TABLE records (
  id INTEGER PRIMARY KEY, year INTEGER NOT NULL, street TEXT NOT NULL,
  street_norm TEXT NOT NULL, number TEXT NOT NULL, complement TEXT,
  neighborhood TEXT, land_area REAL, built_area REAL,
  latitude REAL, longitude REAL, use_type TEXT, postal TEXT, road_code TEXT
);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _norm(value: Any) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    words = re.findall(r"[a-z0-9]+", "".join(c for c in value if not unicodedata.combining(c)))
    prefixes = {"r", "rua", "av", "avenida", "travessa", "alameda", "praca", "pca", "do", "da", "de", "dos", "das"}
    return " ".join(w for w in words if w not in prefixes)


def _number(value: Any) -> str | None:
    raw = str(value or "").strip()
    return str(int(raw)) if raw.isdecimal() else None


def _area(value: Any) -> float | None:
    try:
        n = float(str(value).strip().replace(",", "."))
        return n if math.isfinite(n) and n >= 0 else None
    except (TypeError, ValueError):
        return None


def _coordinates(lat: Any, lon: Any) -> tuple[float | None, float | None]:
    try:
        latitude = float(str(lat).replace(",", "."))
        longitude = float(str(lon).replace(",", "."))
    except (TypeError, ValueError):
        return None, None
    if not (math.isfinite(latitude) and math.isfinite(longitude)
            and -8.35 <= latitude <= -7.75 and -35.2 <= longitude <= -34.7):
        return None, None
    return latitude, longitude


class RecifeIPTULocalStore:
    """Atomic, streamed, private-on-device SQLite import of annual CSV releases."""

    def __init__(self, directory: Path | str | None = None) -> None:
        self.directory = Path(directory or (Path.home() / ".imobhunter" / "recife"))
        self.database = self.directory / "iptu_publico.sqlite3"

    def installed(self) -> bool:
        return self.database.is_file()

    def counts(self) -> dict[int, int]:
        if not self.installed():
            return {}
        with closing(sqlite3.connect(self.database)) as db:
            return dict(db.execute("SELECT year, COUNT(*) FROM records GROUP BY year"))

    def import_files(self, paths: list[Path] | tuple[Path, ...]) -> dict[int, int]:
        files = [Path(p) for p in paths]
        if not 1 <= len(files) <= 3 or len({p.resolve() for p in files}) != len(files):
            raise ValueError("Selecione até três CSVs anuais diferentes de Recife.")
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".recife-", suffix=".sqlite3", dir=self.directory)
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            with closing(sqlite3.connect(tmp)) as db:
                db.executescript(SCHEMA)
                counts: dict[int, int] = {}
                for path in files:
                    if path.suffix.lower() != ".csv" or not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
                        raise ValueError("Arquivo CSV inexistente, vazio ou acima de 300 MB.")
                    with path.open("r", encoding="utf-8-sig", newline="") as stream:
                        reader = csv.DictReader(stream, delimiter=";")
                        if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
                            raise ValueError("CSV não apresenta as colunas públicas de IPTU do Recife.")
                        count = 0
                        file_year = None
                        batch = []
                        for row in reader:
                            count += 1
                            if count > MAX_ROWS_PER_FILE:
                                raise ValueError("CSV excede o limite de 1 milhão de linhas.")
                            try:
                                year = int(row.get("ano do exercício") or "")
                            except ValueError as exc:
                                raise ValueError("Ano fiscal inválido no CSV.") from exc
                            if not 2016 <= year <= 2100 or (file_year is not None and year != file_year):
                                raise ValueError("CSV deve conter apenas um exercício fiscal válido.")
                            file_year = year
                            street = (row.get("logradouro") or "").strip()
                            number = _number(row.get("numero"))
                            norm = _norm(street)
                            if not street or not norm or number is None:
                                continue
                            if (row.get("cidade") or "").strip().casefold() != "recife" or (
                                row.get("estado") or "").strip().upper() != "PE":
                                raise ValueError("O arquivo contém registros de município diferente de Recife/PE.")
                            latitude, longitude = _coordinates(row.get("latitude"), row.get("longitude"))
                            batch.append((
                                year, street[:160], norm[:160], number,
                                (row.get("complemento") or "").strip()[:160],
                                (row.get("bairro") or "").strip()[:80],
                                _area(row.get("AREA TERRENO")), _area(row.get("AREA CONSTRUIDA")),
                                latitude, longitude,
                                (row.get("tipo de uso do imóvel") or "").strip()[:80],
                                (row.get("CEP") or "").strip()[:12],
                                (row.get("Código Logradouro") or "").strip()[:24],
                            ))
                            if len(batch) == 2000:
                                db.executemany(
                                    "INSERT INTO records (year,street,street_norm,number,complement,neighborhood,"
                                    "land_area,built_area,latitude,longitude,use_type,postal,road_code)"
                                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", batch,
                                )
                                batch.clear()
                        if batch:
                            db.executemany(
                                "INSERT INTO records (year,street,street_norm,number,complement,neighborhood,"
                                "land_area,built_area,latitude,longitude,use_type,postal,road_code)"
                                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", batch,
                            )
                        if file_year is None or count == 0:
                            raise ValueError("CSV de IPTU vazio.")
                        if file_year in counts:
                            raise ValueError("Não importe dois arquivos do mesmo exercício.")
                        counts[file_year] = count
                db.execute("CREATE INDEX idx_recife_address ON records(street_norm,number,year)")
                db.executemany("INSERT INTO metadata(key,value) VALUES (?,?)", [
                    ("origin", SOURCE_URL),
                    ("indexed_at", datetime.now(UTC).isoformat()),
                    ("notice", "Sem dados de contribuintes, CPF/CNPJ ou valores tributários"),
                ])
                db.commit()
            os.replace(tmp, self.database)
            if os.name != "nt":
                self.database.chmod(0o600)
            return counts
        finally:
            tmp.unlink(missing_ok=True)

    def search(self, request: SearchRequest, source_id: str = "recife_iptu_local") -> tuple[list[PropertyRecord], dict[str, Any]]:
        diag: dict[str, Any] = {
            "source": source_id, "origin": SOURCE_URL, "query_mode": "local_official_annual_csv",
            "sql_status": "taxpayer_id_not_property_inscription", "geometry_available": False,
        }
        if not self.installed():
            diag["result"] = "local_csv_not_imported"
            return [], diag
        street = _norm(request.address)
        number = _number(request.number)
        if not street or number is None:
            diag["result"] = "street_and_number_required"
            return [], diag
        with closing(sqlite3.connect(self.database)) as db:
            db.row_factory = sqlite3.Row
            year = db.execute("SELECT MAX(year) FROM records").fetchone()[0]
            if year is None:
                diag["result"] = "empty_index"
                return [], diag
            total = db.execute(
                "SELECT COUNT(*) FROM records WHERE street_norm=? AND number=? AND year=?",
                (street, number, year),
            ).fetchone()[0]
            rows = db.execute(
                "SELECT * FROM records WHERE street_norm=? AND number=? AND year=?"
                " ORDER BY id LIMIT ?", (street, number, year, MAX_RESULTS),
            ).fetchall()
            records = []
            for row in rows:
                details = {
                    "source": source_id,
                    "official_source": "Prefeitura do Recife — dados abertos IPTU",
                    "source_url": SOURCE_URL, "fiscal_year": year,
                    "complemento": row["complement"], "bairro": row["neighborhood"],
                    "area_construida_m2": row["built_area"],
                    "tipo_uso_imovel": row["use_type"],
                    "cep": row["postal"], "codigo_logradouro": row["road_code"],
                    "municipal_registration_number": None,
                    "iptu_registration_number": None, "sql": None,
                    "cadastre_match": "exact_address_group_unit_unverified",
                    "sql_status": "taxpayer_id_not_property_inscription",
                    "geometry_status": "coordinates_only_no_parcel_geometry",
                    "owner_status": "not_imported",
                }
                records.append(PropertyRecord(
                    address=f"{row['street']}, {row['number']}", city="Recife", state="PE",
                    area_m2=row["land_area"], latitude=row["latitude"], longitude=row["longitude"],
                    attributes=details,
                    provenance=(Provenance(source_id=source_id, confidence=0.65,
                                           reference=f"IPTU {year} — registro público por endereço"),),
                ))
            diag.update({"result": "address_group_candidates" if rows else "address_not_found_in_latest_csv",
                         "fiscal_year": year, "matching_units": total,
                         "limited_results": total > MAX_RESULTS})
            return records, diag
