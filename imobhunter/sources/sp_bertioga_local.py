"""Local-first Bertioga municipal GeoJSON bundle.

The official export contains lot polygons (with Inscrição, Quadra, Lote,
Emplacamento and Matrícula), street axes and zoning. Source files are
processed ON THE USER'S COMPUTER into an indexed local SQLite database.
No data is sent to the license server or bundled into installers.

A street/number matched against a nearby road centreline is only a
SPATIAL CANDIDATE; never assert a confirmed individual tax registration.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest
from imobhunter.sources.sc_municipal_cadastre import _number, _street_tokens

MAX_FILE_BYTES = 90 * 1024 * 1024
MAX_FEATURES = 50_000
MAX_POINTS_PER_GEOMETRY = 200_000
MAX_ROAD_DISTANCE_M = 75.0
MAX_RESULTS = 12
DB_VERSION = 1
SOURCE_URL = "https://geoportal.bertioga.sp.gov.br/"

SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE lots (
    id INTEGER PRIMARY KEY,
    door TEXT, inscription TEXT, block TEXT, lot TEXT,
    registry TEXT, neighborhood TEXT, development TEXT,
    lon REAL, lat REAL, geometry TEXT NOT NULL
);
CREATE TABLE roads (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL,
    normalized TEXT NOT NULL, postal TEXT, geometry TEXT NOT NULL
);
CREATE TABLE zones (
    id INTEGER PRIMARY KEY, code TEXT, label TEXT, uses TEXT,
    min_lon REAL, min_lat REAL, max_lon REAL, max_lat REAL,
    geometry TEXT NOT NULL
);
CREATE INDEX idx_lots_door ON lots(door);
CREATE INDEX idx_roads_street ON roads(normalized);
"""


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.casefold() not in {"none", "null", "nan", "-"} else None


def _geometry_extent(geom: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(geom, dict) or not isinstance(geom.get("coordinates"), list):
        return None
    bounds = [float("inf"), float("inf"), -float("inf"), -float("inf")]
    n = 0
    def walk(value: Any) -> None:
        nonlocal n
        if isinstance(value, list) and len(value) >= 2 and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in value[:2]
        ):
            lon, lat = float(value[0]), float(value[1])
            if not (-180 <= lon <= 180 and -90 <= lat <= 90
                    and math.isfinite(lon) and math.isfinite(lat)):
                raise ValueError("Coordenada municipal fora do intervalo WGS84.")
            bounds[0] = min(bounds[0], lon)
            bounds[1] = min(bounds[1], lat)
            bounds[2] = max(bounds[2], lon)
            bounds[3] = max(bounds[3], lat)
            n += 1
            if n > MAX_POINTS_PER_GEOMETRY:
                raise ValueError("Geometria excede o limite de vértices.")
        elif isinstance(value, list):
            for child in value:
                walk(child)
        else:
            raise ValueError("Geometria GeoJSON inválida.")
    walk(geom["coordinates"])
    if n == 0:
        return None
    if not (-46.6 <= bounds[0] <= -45.5 and -46.6 <= bounds[2] <= -45.5
            and -24.5 <= bounds[1] <= -23.3 and -24.5 <= bounds[3] <= -23.3):
        raise ValueError("O arquivo não contém coordenadas de Bertioga/SP.")
    return tuple(bounds)


def _read_collection(path: Path, expected: str) -> list[dict]:
    if path.suffix.casefold() not in {".geojson", ".json"}:
        raise ValueError(f"{expected}: selecione arquivo GeoJSON da prefeitura.")
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
        raise ValueError(f"{expected}: arquivo não encontrado ou maior que 90 MB.")
    with path.open(encoding="utf-8-sig") as reader:
        data = json.load(reader)
    features = data.get("features") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection" or not isinstance(features, list):
        raise ValueError(f"{expected}: esperado FeatureCollection GeoJSON.")
    if not 1 <= len(features) <= MAX_FEATURES:
        raise ValueError(f"{expected}: quantidade de feições fora do limite seguro.")
    first = next((x.get("properties") for x in features
                  if isinstance(x, dict) and isinstance(x.get("properties"), dict)), {})
    keys = set(first)
    mandatory = {
        "lotes": {"Inscrição", "Emplacamento", "Quadra", "Lote"},
        "eixos": {"Logardouro", "Codigo Logradouro"},
        "zoneamento": {"sigla", "legenda"},
    }[expected]
    if not mandatory.issubset(keys):
        raise ValueError(f"{expected}: colunas municipais esperadas não encontradas.")
    crs = str(((data.get("crs") or {}).get("properties") or {}).get("name") or "")
    if crs and not any(token in crs.upper() for token in ("CRS84", "4674", "4326")):
        raise ValueError(f"{expected}: sistema de referência não compatível.")
    return features


def _street_name(value: Any) -> str:
    return " ".join(_street_tokens(value))


def _distance_to_line(lon: float, lat: float, geom: Any) -> float:
    coordinates = geom.get("coordinates") if isinstance(geom, dict) else None
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return float("inf")
    scale_x = 111_320.0 * math.cos(math.radians(lat))
    scale_y = 111_320.0
    minimum = float("inf")
    for a, b in pairwise(coordinates):
        if not (isinstance(a, list) and isinstance(b, list)
                and len(a) >= 2 and len(b) >= 2):
            continue
        ax, ay = (a[0] - lon) * scale_x, (a[1] - lat) * scale_y
        bx, by = (b[0] - lon) * scale_x, (b[1] - lat) * scale_y
        dx, dy = bx - ax, by - ay
        t = max(0., min(1., -(ax * dx + ay * dy) / (dx * dx + dy * dy))) \
            if dx * dx + dy * dy else 0.
        distance = math.hypot(ax + t * dx, ay + t * dy)
        minimum = min(minimum, distance)
    return minimum


def _point_in_ring(lon: float, lat: float, ring: Any) -> bool:
    if not isinstance(ring, list) or len(ring) < 4:
        return False
    inside = False
    last = ring[-1]
    for curr in ring:
        if not isinstance(curr, list) or not isinstance(last, list):
            return False
        x1, y1 = last[:2]
        x2, y2 = curr[:2]
        if ((y1 > lat) != (y2 > lat)
                and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1):
            inside = not inside
        last = curr
    return inside


def _point_in_geometry(lon: float, lat: float, geometry: Any) -> bool:
    if not isinstance(geometry, dict):
        return False
    typ = geometry.get("type")
    polys = [geometry.get("coordinates")] if typ == "Polygon" \
        else geometry.get("coordinates") if typ == "MultiPolygon" else []
    if not isinstance(polys, list):
        return False
    for polygon in polys:
        if (
            isinstance(polygon, list)
            and polygon
            and _point_in_ring(lon, lat, polygon[0])
            and not any(_point_in_ring(lon, lat, hole) for hole in polygon[1:])
        ):
            return True
    return False


class BertiogaLocalStore:
    """Install/replace the three official exports atomically in local SQLite."""

    def __init__(self, directory: Path | str | None = None) -> None:
        self.directory = Path(directory or (Path.home() / ".imobhunter" / "bertioga"))
        self.database = self.directory / "municipal_cadastre.sqlite3"

    def installed(self) -> bool:
        return self.database.is_file()

    def counts(self) -> dict[str, int]:
        if not self.installed():
            return {}
        with closing(sqlite3.connect(self.database)) as db:
            return {
                "lotes": db.execute("SELECT COUNT(*) FROM lots").fetchone()[0],
                "logradouros": db.execute("SELECT COUNT(*) FROM roads").fetchone()[0],
                "zonas": db.execute("SELECT COUNT(*) FROM zones").fetchone()[0],
            }

    def import_files(
        self, lots_path: Path, roads_path: Path, zones_path: Path
    ) -> dict[str, int]:
        paths = (Path(lots_path), Path(roads_path), Path(zones_path))
        if len({str(p.resolve()) for p in paths}) != 3:
            raise ValueError("Selecione três arquivos GeoJSON distintos.")
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".bertioga-", suffix=".db", dir=self.directory)
        os.close(fd)
        tmp = Path(name)
        try:
            with closing(sqlite3.connect(tmp)) as db:
                db.executescript(SCHEMA)
                counts: dict[str, int] = {}
                for kind, file_path in zip(("lotes", "eixos", "zoneamento"), paths):
                    features = _read_collection(file_path, kind)
                    count = 0
                    for feature in features:
                        if not isinstance(feature, dict):
                            continue
                        p = feature.get("properties") or {}
                        geom = feature.get("geometry")
                        if not isinstance(p, dict) or not isinstance(geom, dict):
                            continue
                        expected_type = "LineString" if kind == "eixos" else "MultiPolygon"
                        if geom.get("type") != expected_type:
                            continue
                        bounds = _geometry_extent(geom)
                        if bounds is None:
                            continue
                        g = json.dumps(geom, separators=(",", ":"), ensure_ascii=False)
                        if kind == "lotes":
                            door = _number(p.get("Emplacamento"))
                            if door == "0":
                                door = None
                            db.execute(
                                "INSERT INTO lots (door,inscription,block,lot,registry,"
                                "neighborhood,development,lon,lat,geometry) "
                                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                                (door, _clean(p.get("Inscrição")), _clean(p.get("Quadra")),
                                 _clean(p.get("Lote")), _clean(p.get("Matrícula")),
                                 _clean(p.get("Bairro")), _clean(p.get("Loteamento")),
                                 (bounds[0] + bounds[2]) / 2,
                                 (bounds[1] + bounds[3]) / 2, g),
                            )
                        elif kind == "eixos":
                            street = _clean(p.get("Logardouro"))
                            norm = _street_name(street)
                            if not norm:
                                continue
                            db.execute(
                                "INSERT INTO roads (name,normalized,postal,geometry)"
                                " VALUES (?,?,?,?)",
                                (street, norm, _clean(p.get("CEP")), g),
                            )
                        else:
                            db.execute(
                                "INSERT INTO zones (code,label,uses,min_lon,min_lat,"
                                "max_lon,max_lat,geometry) VALUES (?,?,?,?,?,?,?,?)",
                                (_clean(p.get("sigla")), _clean(p.get("legenda")),
                                 _clean(p.get("usos_permitidos")),
                                 *bounds, g),
                            )
                        count += 1
                    del features
                    if not count:
                        raise ValueError(f"{kind}: nenhuma geometria municipal válida.")
                    counts[{"lotes": "lotes", "eixos": "logradouros",
                            "zoneamento": "zonas"}[kind]] = count
                db.executemany("INSERT INTO metadata (key,value) VALUES (?,?)", (
                    ("origin", SOURCE_URL),
                    ("installed_at", datetime.now(UTC).isoformat()),
                    ("version", str(DB_VERSION)),
                    ("source_age", "data de atualização municipal não informada"),
                ))
                db.execute(f"PRAGMA user_version={DB_VERSION}")
                db.commit()
            os.replace(tmp, self.database)
            return counts
        finally:
            tmp.unlink(missing_ok=True)

    def search(
        self, request: SearchRequest, source_id: str = "bertioga_geojson_local",
    ) -> tuple[list[PropertyRecord], dict[str, Any]]:
        diag: dict[str, Any] = {
            "source": source_id, "origin": SOURCE_URL,
            "query_mode": "offline_official_geojson",
            "registration_by_address_verified": False,
            "local_snapshot_date": "municipal publication date not provided",
            "sql_status": "not_individually_verified",
        }
        if not self.installed():
            diag["result"] = "local_bundle_not_imported"
            return [], diag
        if not (_number(request.number) and _street_tokens(request.address)):
            diag["result"] = "street_and_numeric_number_required"
            return [], diag
        door = _number(request.number)
        normalized = _street_name(request.address)
        with sqlite3.connect(self.database) as db:
            db.row_factory = sqlite3.Row
            road_rows = db.execute(
                "SELECT geometry FROM roads WHERE normalized=?", (normalized,),
            ).fetchall()
            if not road_rows:
                diag["result"] = "street_not_found_in_local_axes"
                return [], diag
            roads = [json.loads(r["geometry"]) for r in road_rows]
            lots = db.execute(
                "SELECT * FROM lots WHERE door=?", (door,),
            ).fetchall()
            nearest: list[tuple[float, sqlite3.Row]] = []
            for lot in lots:
                distance = min(
                    _distance_to_line(lot["lon"], lot["lat"], line) for line in roads
                )
                if distance <= MAX_ROAD_DISTANCE_M:
                    nearest.append((distance, lot))
            nearest.sort(key=lambda pair: pair[0])
            selected = nearest[:MAX_RESULTS]
            diag.update({
                "result": "spatial_lot_candidates" if selected else "no_spatial_candidate",
                "matching_road_segments": len(road_rows),
                "lots_with_same_door": len(lots),
                "spatial_candidates": len(nearest),
                "limited_results": len(nearest) > MAX_RESULTS,
                "match_type": "emplacamento_equal_and_near_street_axis_not_confirmed",
            })
            records = []
            for distance, lot in selected:
                zones = []
                for zone in db.execute(
                    "SELECT code,label,uses,geometry FROM zones WHERE "
                    "min_lon<=? AND max_lon>=? AND min_lat<=? AND max_lat>=?",
                    (lot["lon"], lot["lon"], lot["lat"], lot["lat"]),
                ):
                    if _point_in_geometry(lot["lon"], lot["lat"], json.loads(zone["geometry"])):
                        zones.append({
                            "code": zone["code"], "label": zone["label"],
                            "uses": zone["uses"],
                        })
                inscription = lot["inscription"]
                complete = bool(inscription and "#" not in inscription
                                and re.fullmatch(r"[0-9.]+", inscription))
                attrs: dict[str, Any] = {
                    "source": source_id, "official_source": "Geoportal de Bertioga",
                    "source_url": SOURCE_URL,
                    "geometry_geojson": lot["geometry"],
                    "inscricao_cadastral_do_lote_candidato": inscription,
                    "inscricao_status": "publicada_completa" if complete
                                        else "incompleta_ou_ausente",
                    "matricula_informada_no_lote": lot["registry"],
                    "loteamento": lot["development"], "bairro": lot["neighborhood"],
                    "emplacamento_publicado": lot["door"],
                    "zoneamento_candidato": zones[:5],
                    "zoneamento_status": "intersecao_por_centro_geometrico",
                    "distancia_eixo_logradouro_m_estimada": round(distance, 1),
                    "cadastre_match": "spatial_candidate_only",
                    "sql": None, "iptu_registration_number": None,
                    "municipal_registration_number": None,
                    "sql_status": "official_lot_inscription_not_licensed_as_address_sql",
                    "owner_status": "not_requested",
                }
                records.append(PropertyRecord(
                    city="Bertioga", state="SP",
                    address=f"{request.address}, {door}",
                    block=lot["block"], lot=lot["lot"],
                    latitude=lot["lat"], longitude=lot["lon"],
                    attributes=attrs,
                    provenance=(Provenance(
                        source_id=source_id, confidence=0.45,
                        reference="Geoportal Bertioga — lote candidato / sem vinculo fiscal confirmado",
                    ),),
                ))
        return records, diag
