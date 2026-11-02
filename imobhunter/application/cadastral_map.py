"""Trust-aware preparation of official cadastral geometries for the desktop map.

Pure Python: never invent polygon boundaries or treat geocoder coordinates as
official lot geometry. All GeoJSON coordinates are accepted only in WGS84.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any

from imobhunter.domain.identity import canonical_text
from imobhunter.domain.models import PropertyRecord, SearchRequest

Point = tuple[float, float]
Ring = tuple[Point, ...]
Polygon = tuple[Ring, ...]


@dataclass(frozen=True)
class CadastralFeature:
    record: PropertyRecord
    polygons: tuple[Polygon, ...]
    point: Point | None
    classification: str

    @property
    def has_official_polygon(self) -> bool:
        return bool(self.polygons)


def valid_lon_lat(longitude: Any, latitude: Any) -> Point | None:
    try:
        lon, lat = float(longitude), float(latitude)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(lon) or not math.isfinite(lat):
        return None
    if not (-180 <= lon <= 180 and -85.05112878 <= lat <= 85.05112878):
        return None
    return lon, lat


def _ring(raw: Any) -> Ring:
    if not isinstance(raw, (list, tuple)) or len(raw) > 10_000:
        return ()
    # Dropping just one invalid vertex would connect distant points and
    # fabricate a cadastral boundary that the official source never supplied.
    points = []
    for entry in raw:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            return ()
        point = valid_lon_lat(entry[0], entry[1])
        if point is None:
            return ()
        points.append(point)
    if len(set(points)) < 3:
        return ()
    return tuple(points)


def _polygon(raw: Any) -> Polygon:
    if not isinstance(raw, (list, tuple)) or not raw or len(raw) > 128:
        return ()
    outer = _ring(raw[0])
    if not outer:
        return ()
    holes = tuple(_ring(item) for item in raw[1:])
    if any(not ring for ring in holes):
        return ()
    return (outer, *holes)


def parse_geometry(raw: Any) -> tuple[tuple[Polygon, ...], Point | None]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return (), None
    if not isinstance(raw, dict):
        return (), None
    kind, coordinates = raw.get("type"), raw.get("coordinates")
    if kind == "Point" and isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
        return (), valid_lon_lat(coordinates[0], coordinates[1])
    if kind == "Polygon":
        polygon = _polygon(coordinates)
        return (polygon,) if polygon else (), None
    if kind == "MultiPolygon" and isinstance(coordinates, (tuple, list)):
        if len(coordinates) > 256:
            return (), None
        polygons = tuple(polygon for item in coordinates if (polygon := _polygon(item)))
        return polygons, None
    return (), None


def _same_fiscal_value(left: str | None, right: str | None) -> bool:
    """Match fiscal codes without losing their leading-zero representation."""
    if not left or not right:
        return False
    a, b = canonical_text(left), canonical_text(right)
    if a.isdecimal() and b.isdecimal():
        return (a.lstrip("0") or "0") == (b.lstrip("0") or "0")
    return a == b


def _request_matches_parcel(record: PropertyRecord, request: SearchRequest | None) -> bool:
    if request is None or not request.block or not request.lot:
        return False
    if request.state and canonical_text(record.state) != canonical_text(request.state):
        return False
    if request.city and canonical_text(record.city) != canonical_text(request.city):
        return False
    return (
        _same_fiscal_value(request.block, record.block)
        and _same_fiscal_value(request.lot, record.lot)
    )


def classification(
    record: PropertyRecord, request: SearchRequest | None = None
) -> str:
    match = str(record.attributes.get("house_number_match") or "").casefold()
    relation = str(record.attributes.get("parcel_relation") or "").casefold()
    if match == "neighboring_parcel" or relation in {"neighbor_candidate", "neighbor"}:
        return "neighbor"
    if match == "exact":
        return "exact"
    if _request_matches_parcel(record, request):
        return "parcel_query_match"
    if match == "geocoded_spatial_match":
        return "spatial_match"
    if match in {"geocoded_spatial_candidate", "candidate_only"}:
        return "candidate"
    if str(record.attributes.get("cadastre_match") or "") == "spatial_candidate_only":
        return "candidate"
    return "unverified"


CLASSIFICATION_LABELS = {
    "exact": "Número predial confirmado pela fonte",
    "parcel_query_match": "Quadra e lote correspondem à pesquisa no cadastro oficial",
    "spatial_match": "Correspondência espacial geocodificada — conferir número",
    "candidate": "Lote candidato — identificação ainda não confirmada",
    "neighbor": "Lote vizinho — não identificado como imóvel pesquisado",
    "unverified": "Parcela/localização sem correspondência cadastral confirmada",
}


def prepare_features(
    records: list[PropertyRecord] | tuple[PropertyRecord, ...],
    request: SearchRequest | None = None,
) -> tuple[CadastralFeature, ...]:
    """Return usable map features only; no invented geometry or coordinates."""
    features = []
    for record in records:
        polygons, point = parse_geometry(record.attributes.get("geometry_geojson"))
        if point is None and not polygons:
            point = valid_lon_lat(record.longitude, record.latitude)
        if polygons or point:
            features.append(CadastralFeature(record, polygons, point, classification(record, request)))
    return tuple(features)


def preferred_target(features: tuple[CadastralFeature, ...]) -> CadastralFeature | None:
    """Never prefer a neighboring lot or an unverified polygon as the target."""
    ranks = {"exact": 4, "parcel_query_match": 3, "spatial_match": 2, "candidate": 1}
    ranked = sorted(
        (f for f in features if f.classification in ranks),
        key=lambda f: (ranks[f.classification], f.has_official_polygon),
        reverse=True,
    )
    return ranked[0] if ranked else None


def feature_points(feature: CadastralFeature) -> tuple[Point, ...]:
    if feature.polygons:
        return tuple(point for polygon in feature.polygons for ring in polygon for point in ring)
    return (feature.point,) if feature.point else ()


def map_center(features: tuple[CadastralFeature, ...]) -> Point | None:
    target = preferred_target(features)
    selected = target or (features[0] if features else None)
    if selected is None:
        return None
    points = feature_points(selected)
    if not points:
        return None
    return (
        (min(p[0] for p in points) + max(p[0] for p in points)) / 2,
        (min(p[1] for p in points) + max(p[1] for p in points)) / 2,
    )


def sql_from_source(record: PropertyRecord) -> str | None:
    """Only a declared SQL/IPTU value is SQL; generic WFS feature IDs are not."""
    for key in ("iptu_registration_number", "sql"):
        value = record.attributes.get(key)
        if value not in (None, ""):
            return str(value)
    return None
