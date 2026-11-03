"""Safe official-public geospatial coverage for Santo André and Jundiaí.

Municipal portals offer cadastral inspections, but their anonymous WFS
catalogues do NOT currently expose the individual address-to-fiscal
registration join. Return map-only candidates for Jundiaí and explicit
diagnostics for Santo André, never an invented SQL/IPTU, block or lot.
"""
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any

from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest
from imobhunter.sources.sc_municipal_cadastre import _number, _street_tokens

SANTO_ANDRE_WFS = "https://sigamapa.santoandre.sp.gov.br/geoserver/ows"
SANTO_ANDRE_PORTAL = "https://sigamapa.santoandre.sp.gov.br/"
JUNDIAI_WFS = "https://geo.jundiai.sp.gov.br/geoserver/ows"
JUNDIAI_LAYER = "GeoJundiai:lotes_jund"
JUNDIAI_PORTAL = "https://geo.jundiai.sp.gov.br/geojundiai/cfImob.jsp"
MAX_CANDIDATES = 20
Fetch = Callable[[str, dict[str, Any]], Any]
Geocode = Callable[[SearchRequest], tuple[float, float]]


def _coord(point: Any) -> list[float] | None:
    if not isinstance(point, (tuple, list)) or len(point) < 2:
        return None
    try:
        longitude, latitude = float(point[0]), float(point[1])
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(longitude) and math.isfinite(latitude)):
        return None
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        return None
    return [longitude, latitude]


def _polygon(raw: Any) -> tuple[str | None, float | None, float | None]:
    if not isinstance(raw, dict):
        return None, None, None
    geom_type = raw.get("type")
    if geom_type == "Polygon":
        polygons = [raw.get("coordinates")]
    elif geom_type == "MultiPolygon":
        polygons = raw.get("coordinates")
    else:
        return None, None, None
    if not isinstance(polygons, list) or not polygons or len(polygons) > 20:
        return None, None, None
    result = []
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon or len(polygon) > 30:
            return None, None, None
        rings = []
        for ring in polygon:
            if not isinstance(ring, list) or not 4 <= len(ring) <= 2000:
                return None, None, None
            points = [_coord(p) for p in ring]
            if any(point is None for point in points):
                return None, None, None
            if points[0] != points[-1]:
                return None, None, None
            rings.append(points)
        result.append(rings)
    center_ring = result[0][0][:-1]
    lat = sum(p[1] for p in center_ring) / len(center_ring)
    lon = sum(p[0] for p in center_ring) / len(center_ring)
    coordinates = result[0] if geom_type == "Polygon" else result
    return (
        json.dumps({"type": geom_type, "coordinates": coordinates}),
        lat, lon,
    )


def santo_andre(
    request: SearchRequest, fetch: Fetch, source_id: str,
) -> tuple[list[PropertyRecord], dict[str, Any]]:
    """Report verified WFS health but no fictitious fiscal registration."""
    diagnostic: dict[str, Any] = {
        "endpoint": SANTO_ANDRE_WFS,
        "official_portal_url": SANTO_ANDRE_PORTAL,
        "source_id": source_id,
        "query_mode": "public_wfs_capabilities_only",
        "registration_verified": False,
    }
    if not _number(request.number) or not _street_tokens(request.address):
        diagnostic["result"] = "street_and_numeric_number_required"
        return [], diagnostic
    response = fetch(SANTO_ANDRE_WFS, {
        "service": "WFS", "request": "GetCapabilities", "version": "1.1.0",
    })
    root = ET.fromstring(response.content)
    names = [
        (child.text or "").strip()
        for feature in root.iter()
        if feature.tag.rsplit("}", 1)[-1] == "FeatureType"
        for child in feature
        if child.tag.rsplit("}", 1)[-1] == "Name" and child.text
    ]
    if not names:
        raise TypeError("WFS oficial de Santo André sem catálogo válido de camadas.")
    # Only the anonymous WFS is checked. SIGA's fiscal layers are displayed
    # by its web portal but were not present in the public WFS on 2026-11-03.
    fiscal = [
        name for name in names
        if any(t in name.casefold() for t in ("fiscal", "lotes_fiscais", "cadastro"))
    ]
    diagnostic.update({
        "public_layer_count": len(names),
        "public_fiscal_name_candidates": fiscal[:10],
        "result": (
            "fiscal_schema_requires_explicit_address_join_validation"
            if fiscal else "no_public_fiscal_address_layer_in_wfs"
        ),
        "sql_status": "not_verified",
        "cadastre_match": "not_available",
    })
    return [], diagnostic


def jundiai(
    request: SearchRequest, fetch: Fetch, geocode: Geocode, source_id: str,
) -> tuple[list[PropertyRecord], dict[str, Any]]:
    """Only map polygons near a geocoded address, not identified fiscal lots."""
    diagnostic: dict[str, Any] = {
        "endpoint": JUNDIAI_WFS,
        "layer": JUNDIAI_LAYER,
        "official_portal_url": JUNDIAI_PORTAL,
        "query_mode": "bounded_spatial_candidates_only",
        "registration_verified": False,
    }
    if not _number(request.number) or not _street_tokens(request.address):
        diagnostic["result"] = "street_and_numeric_number_required"
        return [], diagnostic
    latitude, longitude = geocode(request)
    # Conservative municipal envelope; do not query a remote city after a
    # misgeocoding. This is NOT an address-to-parcel identity assertion.
    if not (-23.50 <= latitude <= -22.98 and -47.15 <= longitude <= -46.60):
        diagnostic["result"] = "geocoding_outside_jundiai_region"
        return [], diagnostic
    delta = 0.00045
    bbox = (
        f"{longitude - delta:.6f},{latitude - delta:.6f},"
        f"{longitude + delta:.6f},{latitude + delta:.6f},EPSG:4326"
    )
    payload = fetch(JUNDIAI_WFS, {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": JUNDIAI_LAYER,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "bbox": bbox,
        "maxFeatures": MAX_CANDIDATES,
    }).json()
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise TypeError("GeoJundiaí não retornou uma coleção GeoJSON pública válida.")
    results = []
    for feature in payload["features"][:MAX_CANDIDATES]:
        if not isinstance(feature, dict):
            continue
        geojson, center_lat, center_lon = _polygon(feature.get("geometry"))
        if not geojson:
            continue
        attrs = feature.get("properties") or {}
        if not isinstance(attrs, dict):
            attrs = {}
        gid = attrs.get("gid")
        results.append(PropertyRecord(
            property_id=str(gid) if gid is not None else None,
            address=None,
            city="Jundiaí", state="SP",
            block=None, lot=None, area_m2=None,
            latitude=center_lat, longitude=center_lon,
            attributes={
                "source": source_id,
                "official_source": "GeoJundiaí — lotes_jund (cartografia pública)",
                "service_url": JUNDIAI_WFS,
                "official_portal_url": JUNDIAI_PORTAL,
                "service_type": "WFS",
                "geometry_geojson": geojson,
                "map_feature_id": str(gid) if gid is not None else None,
                "municipal_registration_number": None,
                "iptu_registration_number": None,
                "sql": None,
                "sql_status": "not_provided_by_public_wfs",
                "iptu_status": "not_provided_by_public_wfs",
                "cadastre_match": "spatial_candidate_only",
                "owner_status": "not_requested",
            },
            provenance=(Provenance(
                source_id=source_id, confidence=0.2,
                reference=str(gid or ""),
            ),),
        ))
    diagnostic.update({
        "spatial_candidates": len(results),
        "polygon_count": len(results),
        "registration_count": 0,
        "result": (
            "spatial_candidates_without_fiscal_identity"
            if results else "no_public_polygon_near_geocoded_address"
        ),
        "sql_status": "not_provided_by_public_wfs",
        "geocoded_coordinate": {"latitude": latitude, "longitude": longitude},
    })
    return results, diagnostic
