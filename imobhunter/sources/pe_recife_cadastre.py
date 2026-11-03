"""Recife official ESIG parcel lookup by public street/number fields.

Search the municipal polygon layer directly, instead of depending on the
IPTU CKAN portal's uptime. SEQIMOVEL is Recife's municipal real-estate
sequence (not Sao Paulo's SQL). Never read owner/taxpayer information.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest
from imobhunter.sources.sc_municipal_cadastre import (
    _field, _float, _geometry, _number, _number_matches,
    _query, _query_token, _street_matches,
)

RECIFE_LOTS = (
    "https://esigportal2.recife.pe.gov.br/arcgis/rest/services/"
    "Planejamento/BASES_BAIRRO_FACEQUADRA_LOGRADOURO_LOTE/MapServer/3"
)
RECIFE_LOTS_FEATURE = RECIFE_LOTS.replace("/MapServer/", "/FeatureServer/")
Fetch = Callable[[str, dict[str, Any]], Any]


def recife_parcels(
    request: SearchRequest, fetch: Fetch, source_id: str,
) -> tuple[list[PropertyRecord], dict[str, Any]]:
    number = _number(request.number)
    token = _query_token(request.address or "")
    diagnostic: dict[str, Any] = {
        "endpoint": RECIFE_LOTS,
        "alternate_endpoint": RECIFE_LOTS_FEATURE,
        "query_mode": "exact_official_street_and_number",
        "identifier_kind": "Recife municipal sequential real-estate code",
    }
    if not number or not token:
        diagnostic["result"] = "street_and_numeric_number_required"
        return [], diagnostic
    # Only a normalized alphanumeric street token and decimal number enter
    # the read-only ArcGIS query, never arbitrary user-provided SQL.
    where = f"NMENDCOMP LIKE '%{token}%' AND ENDNUMERO = {number}"
    attempts = []
    features: list[dict[str, Any]] = []
    selected_url = RECIFE_LOTS
    for url in (RECIFE_LOTS, RECIFE_LOTS_FEATURE):
        selected_url = url
        try:
            features = _query(fetch, url, where, geometry=True)
            attempts.append({"url": url, "features": len(features), "result": "ok"})
            # A valid empty response can be retried on the municipality's other
            # *documented* read-only ArcGIS layer, but never with a broad bbox.
            if features:
                break
        except (httpx.HTTPError, ValueError, TypeError, RuntimeError) as exc:
            attempts.append({"url": url, "result": type(exc).__name__})
    diagnostic["attempts"] = attempts
    diagnostic["candidate_count"] = len(features)
    if not any(item["result"] == "ok" for item in attempts):
        diagnostic["result"] = "all_official_services_unavailable"
        return [], diagnostic

    results: list[PropertyRecord] = []
    for feature in features:
        fields = feature.get("attributes") or {}
        if not isinstance(fields, dict):
            continue
        street = _field(fields, "NMENDCOMP")
        door_number = _field(fields, "ENDNUMERO")
        if not _street_matches(request.address or "", street):
            continue
        if not _number_matches(number, door_number):
            continue
        geometry, latitude, longitude = _geometry(feature)
        block, lot = _field(fields, "QUADRA"), _field(fields, "LOTE")
        sequence = _field(fields, "SEQIMOVEL")
        sequence = str(sequence).strip() if sequence is not None else None
        if sequence and not any(ch in "123456789" for ch in sequence):
            sequence = None
        dsqfl = _field(fields, "DSQFL")
        source_fields = {
            field: _field(fields, field)
            for field in (
                "OBJECTID", "NMENDCOMP", "ENDNUMERO", "DISTRITO", "SETOR",
                "QUADRA", "FACE", "LOTE", "SEQIMOVEL", "DSQFL", "AREALOTE",
            )
            if _field(fields, field) is not None
        }
        results.append(PropertyRecord(
            property_id=str(_field(fields, "OBJECTID") or "") or None,
            address=f"{street}, {door_number}",
            city="Recife", state="PE",
            block=str(block) if block is not None else None,
            lot=str(lot) if lot is not None else None,
            area_m2=_float(_field(fields, "AREALOTE")),
            latitude=latitude, longitude=longitude,
            attributes={
                "source": source_id,
                "official_source": "Prefeitura do Recife — ESIG Lotes",
                "service_type": "ArcGIS REST",
                "service_url": selected_url,
                "source_properties": source_fields,
                "geometry_geojson": geometry,
                "municipal_registration_number": sequence,
                "iptu_registration_number": sequence,
                "municipal_sequence_number": sequence,
                "parcel_identifier": str(dsqfl) if dsqfl is not None else None,
                "sql": None,
                "sql_status": "not_applicable_sp_sql",
                "iptu_status": "municipal_sequence_from_official_layer" if sequence else "not_published",
                "cadastre_match": "exact_address_match",
                "owner_status": "not_requested",
            },
            provenance=(Provenance(
                source_id=source_id,
                confidence=0.95,
                reference=str(dsqfl or sequence or _field(fields, "OBJECTID") or ""),
            ),),
        ))
    diagnostic.update({
        "result": "exact_address_records" if results else "no_exact_address_match",
        "exact_match_count": len(results),
        "registration_count": sum(bool(x.attributes["iptu_registration_number"]) for x in results),
        "polygon_count": sum(bool(x.attributes["geometry_geojson"]) for x in results),
        "block_count": sum(bool(x.block) for x in results),
        "lot_count": sum(bool(x.lot) for x in results),
    })
    return results, diagnostic
