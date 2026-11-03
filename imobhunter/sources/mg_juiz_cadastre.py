"""Juiz de Fora public cadastral inscription joined to official lot polygons.

A municipal address point contains INSCID, Logradouro, Numero and loteid.
The second public service contains quadra, numero_lot and the polygon. Match
by loteid only; never identify a property from a nearby or unrelated polygon.
"""
from __future__ import annotations

import math
from collections.abc import Callable
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
    if keys:
        features = _query(
            fetch, JUIZ_PARCELS, "loteid IN (" + ", ".join(keys) + ")",
            geometry=True,
        )
        for feature in features:
            attrs = feature.get("attributes") or {}
            if not isinstance(attrs, dict):
                continue
            key = _lot_key(_field(attrs, "loteid"))
            if key in keys and _geometry(feature)[0]:
                polygons.setdefault(key, []).append(feature)
        diagnostic["parcel_candidates"] = len(features)
    else:
        diagnostic["parcel_candidates"] = 0

    results: list[PropertyRecord] = []
    for feature, inscription, lot_id in matched:
        attrs = feature["attributes"]
        parcel_matches = polygons.get(lot_id, []) if lot_id is not None else []
        # More than one polygon for the same ID is ambiguous: no forced quadra/lot.
        parcel = parcel_matches[0] if len(parcel_matches) == 1 else {}
        parcel_props = parcel.get("attributes") or {}
        geom, lat, lon = _geometry(parcel)
        block = _field(parcel_props, "quadra")
        lot = _field(parcel_props, "numero_lot")
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
                    "unique_loteid_match" if len(parcel_matches) == 1
                    else "ambiguous_loteid" if parcel_matches
                    else "parcel_not_returned"
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
