from __future__ import annotations

import csv
import math
import sqlite3
import re
import unicodedata
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
 id INTEGER PRIMARY KEY,
 name TEXT NOT NULL,
 cnpj TEXT DEFAULT '',
 cnae TEXT DEFAULT '',
 address TEXT DEFAULT '',
 city TEXT DEFAULT '',
 state TEXT DEFAULT '',
 latitude REAL,
 longitude REAL,
 revenue_reported REAL,
 revenue_period TEXT DEFAULT '',
 revenue_estimate REAL,
 estimate_method TEXT DEFAULT '',
 source TEXT DEFAULT '',
 updated_at TEXT DEFAULT ''
)
"""


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers."""
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def _segment_matches(value: Any, segment: str) -> bool:
    """Match a market segment against Brazilian CNAE prefixes or common OSM tags."""
    if not segment:
        return True
    raw = str(value or "").strip().casefold()
    normalized = unicodedata.normalize("NFKD", raw)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    digits = re.sub(r"\D", "", raw)
    prefix = int(digits[:2]) if len(digits) >= 2 else None
    wanted = unicodedata.normalize("NFKD", segment.casefold())
    wanted = "".join(char for char in wanted if not unicodedata.combining(char))

    if wanted in {"comercio", "trade"}:
        return (prefix is not None and 45 <= prefix <= 47) or any(
            term in normalized for term in (
                "comerc", "trade", "retail", "shop", "market", "supermarket",
                "convenience", "loja", "varejo", "atacad",
            )
        )
    if wanted in {"industria", "industry"}:
        return (prefix is not None and 10 <= prefix <= 33) or any(
            term in normalized for term in ("industrial", "manufactur", "factory", "industria")
        )
    if wanted in {"construcao", "construction"}:
        return (prefix is not None and 41 <= prefix <= 43) or any(
            term in normalized for term in ("construction", "construcao", "contractor", "empreiteira")
        )
    if wanted in {"servicos", "services"}:
        return (prefix is not None and 49 <= prefix <= 99) or any(
            term in normalized for term in (
                "serv", "office", "amenity", "restaurant", "cafe", "bank", "pharmacy",
                "clinic", "hospital", "fuel", "school", "university", "coworking",
                "craft", "dentist", "repair", "hotel",
            )
        )
    return wanted in normalized


def _number(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(str(value).strip().replace(",", "."))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


class MarketIntelligenceStore:
    """Local-first company store. Import only data the user is allowed to use."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def import_csv(self, csv_path: str | Path) -> int:
        """Import a CSV with headers matching the documented ImobHunter schema."""
        imported = 0
        with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("O CSV está vazio ou não possui cabeçalhos.")
            normalized = {name.strip().lower() for name in reader.fieldnames if name}
            if not {"name", "latitude", "longitude"}.issubset(normalized):
                raise ValueError("O CSV precisa conter as colunas name, latitude e longitude.")
            for row in reader:
                row = {(key or "").strip().lower(): (value or "").strip() for key, value in row.items()}
                name = row.get("name", "").strip()
                lat, lon = _number(row.get("latitude")), _number(row.get("longitude"))
                if not name or lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                    continue
                with self._connect() as db:
                    db.execute(
                        """INSERT INTO businesses
                        (name,cnpj,cnae,address,city,state,latitude,longitude,revenue_reported,
                         revenue_period,revenue_estimate,estimate_method,source,updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (name, row.get("cnpj",""), row.get("cnae",""), row.get("address",""),
                         row.get("city",""), row.get("state","").upper(), lat, lon,
                         _number(row.get("revenue_reported")), row.get("revenue_period",""),
                         _number(row.get("revenue_estimate")), row.get("estimate_method",""),
                         row.get("source",""), row.get("updated_at",""))
                    )
                imported += 1
        return imported

    def import_osm_businesses(self, places: list[dict[str, Any]]) -> int:
        """Persist named, geolocated OSM businesses locally, avoiding duplicate refreshes."""
        imported = 0
        with self._connect() as db:
            for place in places:
                name = str(place.get("name") or "").strip()
                lat, lon = _number(place.get("latitude")), _number(place.get("longitude"))
                if not name or lat is None or lon is None:
                    continue
                address = str(place.get("address") or "").strip()
                source = str(place.get("source") or "OpenStreetMap")
                exists = db.execute(
                    """SELECT id FROM businesses
                       WHERE name=? AND latitude=? AND longitude=? AND source LIKE 'OpenStreetMap%'""",
                    (name, lat, lon),
                ).fetchone()
                if exists:
                    continue
                db.execute(
                    """INSERT INTO businesses
                       (name,cnae,address,city,state,latitude,longitude,source,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    (name, str(place.get("cnae") or ""), address,
                     str(place.get("city") or ""), str(place.get("state") or ""),
                     lat, lon, source),
                )
                imported += 1
        return imported

    def search_radius(self, latitude: float, longitude: float, radius_km: float,
                      segment: str = "") -> list[dict[str, Any]]:
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("Coordenadas inválidas.")
        if not (0 < radius_km <= 500):
            raise ValueError("O raio precisa estar entre 0 e 500 km.")
        # Bounding box keeps the local query inexpensive; haversine does the final test.
        lat_delta = radius_km / 110.574
        cos_lat = max(0.01, abs(math.cos(math.radians(latitude))))
        lon_delta = min(180.0, radius_km / (111.320 * cos_lat))
        with self._connect() as db:
            rows = db.execute(
                """SELECT * FROM businesses
                   WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?""",
                (max(-90, latitude-lat_delta), min(90, latitude+lat_delta),
                 max(-180, longitude-lon_delta), min(180, longitude+lon_delta))
            ).fetchall()
        found = []
        for row in rows:
            item = dict(row)
            if not _segment_matches(item.get("cnae"), segment):
                continue
            distance = haversine_km(latitude, longitude, item["latitude"], item["longitude"])
            if distance <= radius_km:
                item["distance_km"] = round(distance, 2)
                item["revenue_status"] = (
                    "Divulgado" if item.get("revenue_reported") is not None
                    else "Estimativa" if item.get("revenue_estimate") is not None
                    else "Indisponível"
                )
                found.append(item)
        return sorted(found, key=lambda item: item["distance_km"])

    def count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM businesses").fetchone()[0])
