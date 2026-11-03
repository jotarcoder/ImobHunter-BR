"""Juiz de Fora public cadastral inscription joined to official lot polygons.

A municipal address point contains INSCID, Logradouro, Numero and loteid.
The second public service contains quadra, numero_lot and the polygon. Match
by loteid only; never identify a property from a nearby or unrelated polygon.
"""
from __future__ import annotations

import math
from collections.abc import Callable

import httpx
from typing import Any

from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest
from imobhunter.sources.sc_municipal_cadastre import (
    _field, _float, _geometry, _number, _number_matches,
    _query, _query_token, _street_matches,
)

JUIZ_INSCRIPTIONS = (
    "https://sisurb.pjf.mg.gov.br/server/rest/services/"
    "SISURB_cadastro/inscricoes_imobiliarias_geocentro/MapServer/27"
)
JUIZ_PARCELS = (
    "https://sisurb.pjf.mg.gov.br/server/rest/services/"
    "SISURB_cadastro/Cadastro_Recadastramento_2026_08_10/MapServer/0"
)
JUIZ_PARCELS_LEGACY = (
    "https://sisurb.pjf.mg.gov.br/server/rest/services/"
    "Cadastro_lotes_s2000/FeatureServer/0"
)
Fetch = Callable[[str, dict[str, Any]], Any]


def _lot_key(value: Any) -> str | None:
    """Return a safe ArcGIS numeric loteid; never interpolate arbitrary text."""
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
        if math.isfinite(number) and 0 < number < 10**14 and number.is_integer():
            return str(int(number))
    except (TypeError, ValueError):
        pass
    return None


def _valid_inscription(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or len(text) > 80 or not any(char in "123456789" for char in text):
        return None
    return text


def juiz_de_fora(
    request: SearchRequest, fetch: Fetch, source_id: str,
) -> tuple[list[PropertyRecord], dict[str, Any]]:
    number, token = _number(request.number), _query_token(request.address or "")
    diagnostic: dict[str, Any] = {
        "endpoint": JUIZ_INSCRIPTIONS,
        "parcel_endpoint": JUIZ_PARCELS,
        "query_mode": "municipal_address_and_loteid_join",
    }
    if not number or not token:
        diagnostic["result"] = "street_and_numeric_number_required"
        return [], diagnostic

    where = f"Logradouro LIKE '%{token}%' AND Numero = '{number}'"
    points = _query(fetch, JUIZ_INSCRIPTIONS, where, geometry=False)
    matched = []
    for feature in points:
        attrs = feature.get("attributes") or {}
        if not isinstance(attrs, dict):
            continue
        street = _field(attrs, "Logradouro")
        municipal_number = _field(attrs, "Numero")
        if not _street_matches(request.address or "", street):
            continue
        if not _number_matches(number, municipal_number):
            continue
        inscription = _valid_inscription(_field(attrs, "INSCID"))
        if inscription is None:
            continue
        matched.append((feature, inscription, _lot_key(_field(attrs, "loteid"))))
    diagnostic["address_candidate_count"] = len(points)
    diagnostic["exact_inscription_count"] = len(matched)
    if not matched:
        diagnostic["result"] = "no_exact_municipal_address_with_inscription"
        return [], diagnostic

    # Only numeric loteids supplied by confirmed municipal address rows.
    keys = sorted({key for _feature, _inscription, key in matched if key is not None})
    polygons: dict[str, list[dict[str, Any]]] = {}
    legacy: dict[str, list[dict[str, Any]]] = {}
    if keys:
        ids_where = "loteid IN (" + ", ".join(keys) + ")"
        try:
            features = _query(fetch, JUIZ_PARCELS, ids_where, geometry=True)
        except (httpx.HTTPError, ValueError, TypeError, RuntimeError) as exc:
            # The address inscription is already verified; optional parcel
            # enrichment must never erase it when a layer is unavailable.
            diagnostic["parcel_source_error"] = type(exc).__name__
            features = []
        for feature in features:
            attrs = feature.get("attributes") or {}
            if not isinstance(attrs, dict):
                continue
            key = _lot_key(_field(attrs, "loteid"))
            if key in keys:
                polygons.setdefault(key, []).append(feature)
        diagnostic["parcel_candidates"] = len(features)

        # Older public, non-personal lot layer supplies numero_lote/quadra.
        # Use the same official loteid; never infer from spatial proximity.
        needs_legacy = any(
            not (
                len(polygons.get(key, [])) == 1
                and _field(polygons[key][0].get("attributes") or {}, "quadra") is not None
                and _field(polygons[key][0].get("attributes") or {}, "numero_lot") is not None
            )
            for key in keys
        )
        if needs_legacy:
            try:
                old_features = _query(
                    fetch, JUIZ_PARCELS_LEGACY, ids_where, geometry=True,
                )
                for feature in old_features:
                    attrs = feature.get("attributes") or {}
                    if not isinstance(attrs, dict):
                        continue
                    key = _lot_key(_field(attrs, "loteid"))
                    if key in keys:
                        legacy.setdefault(key, []).append(feature)
                diagnostic["legacy_parcel_candidates"] = len(old_features)
            except (httpx.HTTPError, ValueError, TypeError, RuntimeError) as exc:
                diagnostic["legacy_parcel_error"] = type(exc).__name__
    else:
        diagnostic["parcel_candidates"] = 0

    results: list[PropertyRecord] = []
    for feature, inscription, lot_id in matched:
        attrs = feature["attributes"]
        parcel_matches = polygons.get(lot_id, []) if lot_id is not None else []
        legacy_matches = legacy.get(lot_id, []) if lot_id is not None else []
        # Never pick the first polygon if a loteid appears multiple times.
        parcel = parcel_matches[0] if len(parcel_matches) == 1 else {}
        older = legacy_matches[0] if len(legacy_matches) == 1 else {}
        parcel_props = parcel.get("attributes") or {}
        older_props = older.get("attributes") or {}
        geom, lat, lon = _geometry(parcel)
        if geom is None:
            geom, lat, lon = _geometry(older)
        current_block = _field(parcel_props, "quadra")
        old_block = _field(older_props, "quadra")
        current_lot = _field(parcel_props, "numero_lot")
        old_lot = _field(older_props, "numero_lote")
        # If public layers disagree, expose no misleading block/lot.
        block = (
            None if current_block is not None and old_block is not None
            and str(current_block) != str(old_block)
            else current_block if current_block is not None else old_block
        )
        lot = (
            None if current_lot is not None and old_lot is not None
            and str(current_lot) != str(old_lot)
            else current_lot if current_lot is not None else old_lot
        )
        official_street = _field(attrs, "Logradouro")
        official_number = _field(attrs, "Numero")
        source_fields = {
            name: _field(attrs, name)
            for name in ("INSCID", "Logradouro", "Numero", "loteid", "Area_Lote")
            if _field(attrs, name) is not None
        }
        results.append(PropertyRecord(
            property_id=(
                str(_field(attrs, "OBJECTID"))
                if _field(attrs, "OBJECTID") is not None else None
            ),
            address=f"{official_street}, {official_number}",
            city="Juiz de Fora", state="MG",
            block=str(block) if block is not None else None,
            lot=str(lot) if lot is not None else None,
            area_m2=_float(_field(attrs, "Area_Lote")),
            latitude=lat, longitude=lon,
            attributes={
                "source": source_id,
                "official_source": "Prefeitura de Juiz de Fora — SISURB Cadastro",
                "service_url": JUIZ_INSCRIPTIONS,
                "parcel_source_url": JUIZ_PARCELS,
                "parcel_fallback_source_url": JUIZ_PARCELS_LEGACY if older else None,
                "service_type": "ArcGIS REST",
                "source_properties": source_fields,
                "geometry_geojson": geom,
                "parcel_identifier": lot_id,
                "municipal_registration_number": inscription,
                "iptu_registration_number": inscription,
                "sql": None,
                "sql_status": "not_applicable_sp_sql",
                "iptu_status": "provided_by_layer",
                "parcel_join_status": (
                    "unique_loteid_match"
                    if len(parcel_matches) == 1 or len(legacy_matches) == 1
                    else "ambiguous_loteid"
                    if parcel_matches or legacy_matches
                    else "parcel_not_returned"
                ),
                "block_lot_source": (
                    JUIZ_PARCELS_LEGACY
                    if older and (current_block is None or current_lot is None)
                    else JUIZ_PARCELS if block is not None or lot is not None
                    else None
                ),
                "cadastre_match": "exact_address_match",
                "owner_status": "not_requested",
            },
            provenance=(Provenance(
                source_id=source_id, confidence=0.95, reference=inscription,
            ),),
        ))
    diagnostic.update({
        "result": "exact_address_records",
        "record_count": len(results),
        "registration_count": len(results),
        "polygon_count": sum(bool(rec.attributes["geometry_geojson"]) for rec in results),
        "block_count": sum(bool(rec.block) for rec in results),
        "lot_count": sum(bool(rec.lot) for rec in results),
    })
    return results, diagnostic
