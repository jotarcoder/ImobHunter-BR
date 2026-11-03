"""Official Caxias do Sul parcel lookup, never attributing a nearby parcel.

The public MapViewerPublico lot layer publishes a *lot inscription*, which
must not be mislabeled an individual IPTU/SQL registration. The quadra
number is read from the separate official polygon layer only if unambiguous.
"""
from __future__ import annotations

import json
from collections.abc import Callable

import httpx
from typing import Any

from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest
from imobhunter.sources.sc_municipal_cadastre import (
    _field,
    _float,
    _geometry,
    _number,
    _number_matches,
    _query,
    _query_token,
    _street_matches,
)

CAXIAS_LOTS = (
    "https://gis.caxias.rs.gov.br/server/rest/services/"
    "MapViewerPublico/FeatureServer/3"
)
CAXIAS_BLOCKS = (
    "https://gis.caxias.rs.gov.br/server/rest/services/"
    "MapViewerPublico/FeatureServer/4"
)
CAXIAS_MAP_LOTS = CAXIAS_LOTS.replace("/FeatureServer/", "/MapServer/")
CAXIAS_MAP_BLOCKS = CAXIAS_BLOCKS.replace("/FeatureServer/", "/MapServer/")
Fetch = Callable[[str, dict[str, Any]], Any]
MAX_BLOCKS = 6


def _official_block(
    fetch: Fetch, lot_geometry: str | None,
) -> tuple[str | None, dict[str, Any]]:
    """Only associate a quadra whose polygon contains the whole lot polygon."""
    if not lot_geometry:
        return None, {"result": "no_usable_lot_polygon"}
    coordinates = json.loads(lot_geometry)["coordinates"]
    params = {
        "where": "1=1",
        "geometry": json.dumps({
            "rings": coordinates,
            "spatialReference": {"wkid": 4326},
        }),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelContains",
        "outFields": "inscricaonrquadra,inscricaoquadra",
        "returnGeometry": "false",
        "f": "json",
        "resultRecordCount": MAX_BLOCKS,
    }
    errors = []
    payload = None
    original_error: Exception | None = None
    for block_url in (CAXIAS_BLOCKS, CAXIAS_MAP_BLOCKS):
        try:
            response = fetch(block_url + "/query", params)
            candidate = response.json()
            if isinstance(candidate, dict) and isinstance(candidate.get("features"), list):
                payload = candidate
                break
        except (httpx.HTTPError, ValueError, TypeError, RuntimeError) as exc:
            if original_error is None:
                original_error = exc
            errors.append(type(exc).__name__)
    if payload is None:
        # Keep the underlying transport exception visible to diagnostics,
        # rather than hiding SSL, network timeouts or HTTP errors as TypeError.
        if original_error is not None:
            raise original_error
        raise TypeError(f"ArcGIS quadras retornou JSON inválido: {errors!r}")
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        error = payload.get("error") if isinstance(payload, dict) else type(payload).__name__
        raise TypeError(f"ArcGIS quadras retornou JSON inválido: {error!r}")
    blocks = {
        str(value)
        for feature in payload["features"]
        if isinstance(feature, dict) and isinstance(feature.get("attributes"), dict)
        if (value := _field(feature["attributes"], "inscricaonrquadra")) is not None
    }
    # Do not select the first adjacent/ambiguous quadra.
    if len(blocks) != 1 or len(payload["features"]) >= MAX_BLOCKS:
        return None, {
            "result": "no_single_official_quadra",
            "number_of_matches": len(payload["features"]),
            "distinct_quadra_count": len(blocks),
        }
    block = next(iter(blocks))
    return block, {"result": "official_quadra_intersection", "quadra": block}


def caxias_do_sul(
    request: SearchRequest, fetch: Fetch, source_id: str,
) -> tuple[list[PropertyRecord], dict[str, Any]]:
    number = _number(request.number)
    token = _query_token(request.address or "")
    diagnostic: dict[str, Any] = {
        "endpoint": CAXIAS_LOTS,
        "quadra_endpoint": CAXIAS_BLOCKS,
        "query_mode": "exact_official_street_and_number",
    }
    if not number or not token:
        diagnostic["result"] = "street_and_numeric_number_required"
        return [], diagnostic

    # Numeric number and sanitized street token only; no arbitrary user SQL.
    where = f"nm_logradouro LIKE '%{token}%' AND nr_imovel = '{number}'"
    errors: list[str] = []
    features = []
    lot_source = CAXIAS_LOTS
    for lot_url in (CAXIAS_LOTS, CAXIAS_MAP_LOTS):
        try:
            features = _query(fetch, lot_url, where, geometry=True)
            lot_source = lot_url
            if features:
                break
        except (httpx.HTTPError, ValueError, TypeError, RuntimeError) as exc:
            errors.append(f"{lot_url.rsplit('/', 2)[-2]}: {type(exc).__name__}")
    diagnostic["endpoint_attempt_errors"] = errors
    diagnostic["selected_lot_endpoint"] = lot_source
    diagnostic["candidate_count"] = len(features)
    if not features and len(errors) == 2:
        diagnostic["result"] = "both_official_lot_services_unavailable"
        return [], diagnostic
    results: list[PropertyRecord] = []
    for feature in features:
        attrs = feature.get("attributes") or {}
        if not isinstance(attrs, dict):
            continue
        official_street = _field(attrs, "nm_logradouro")
        official_number = _field(attrs, "nr_imovel")
        if not _street_matches(request.address or "", official_street):
            continue
        if not _number_matches(number, official_number):
            continue
        inscription = _field(attrs, "inscricaoloteponto")
        geom, latitude, longitude = _geometry(feature)
        try:
            block, block_diagnostic = _official_block(fetch, geom)
        except (httpx.HTTPError, ValueError, TypeError, RuntimeError) as exc:
            # Quadra is optional enrichment; never discard a verified address
            # and fiscal lot inscription because the second service is offline.
            block, block_diagnostic = None, {
                "result": "quadra_source_error",
                "error_type": type(exc).__name__,
            }
        official_area = _float(_field(attrs, "vlr_area_real"))
        source_fields = {
            key: attrs.get(key)
            for key in (
                "codigolote", "inscricaoloteponto", "nm_logradouro", "nr_imovel",
                "nm_bairro", "vlr_area_real",
            )
            if key in attrs
        }
        results.append(PropertyRecord(
            property_id=(
                str(_field(attrs, "codigolote"))
                if _field(attrs, "codigolote") is not None else None
            ),
            address=f"{official_street}, {official_number}",
            city="Caxias do Sul", state="RS",
            block=block,
            lot=None,  # This layer publishes a lot *inscription*, not the lot number.
            area_m2=official_area,
            latitude=latitude, longitude=longitude,
            attributes={
                "source": source_id,
                "official_source": "Prefeitura de Caxias do Sul — MapViewer Público",
                "service_url": lot_source,
                "quadra_source_url": CAXIAS_BLOCKS,
                "service_type": "ArcGIS REST",
                "source_properties": source_fields,
                "geometry_geojson": geom,
                "parcel_identifier": str(inscription) if inscription is not None else None,
                "lot_registration_number": str(inscription) if inscription is not None else None,
                "municipal_registration_number": None,
                "iptu_registration_number": None,
                "sql": None,
                "sql_status": "not_provided_by_layer",
                "iptu_status": "not_verified_individual_registration",
                "quadra_match": block_diagnostic["result"],
                "quadra_diagnostics": block_diagnostic,
                "cadastre_match": "exact_address_match",
                "owner_status": "not_provided_by_layer",
            },
            provenance=(Provenance(
                source_id=source_id, confidence=0.9,
                reference=str(inscription or _field(attrs, "codigolote") or ""),
            ),),
        ))
    diagnostic.update({
        "exact_match_count": len(results),
        "polygon_count": sum(bool(item.attributes["geometry_geojson"]) for item in results),
        "quadra_count": sum(bool(item.block) for item in results),
        "lot_inscription_count": sum(
            bool(item.attributes["lot_registration_number"]) for item in results
        ),
        "result": "exact_address_records" if results else "no_exact_address_match",
    })
    return results, diagnostic
