"""Exact public municipal address lookups for Joinville and São Bento do Sul.

Never infer ownership, tax debts or an individual inscription from a nearby
polygon. Only the municipality's own address fields can establish an address
match. São Bento do Sul joins records by the published geolot identifier.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Callable
from typing import Any

from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest

JOINVILLE_LAYER = (
    "https://geo.joinville.sc.gov.br/server/rest/services/"
    "SEFAZ/lotes_joinsgc_sefaz/MapServer/0"
)
SAO_BENTO_SERVICE = (
    "https://geo.saobentodosul.sc.gov.br/server/rest/services/"
    "integracao/Cadastro_Imobiliario/MapServer"
)
MAX_RESULTS = 40
Fetch = Callable[[str, dict[str, Any]], Any]
STREET_PREFIXES = {
    "rua", "r", "avenida", "av", "avd", "praca", "pca", "travessa",
    "alameda", "rodovia", "estrada", "do", "da", "de", "dos", "das",
}


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _street_tokens(value: Any) -> list[str]:
    return [word for word in _normalize(value).split() if word not in STREET_PREFIXES]


def _street_matches(expected: str, official: Any) -> bool:
    wanted = _street_tokens(expected)
    available = _street_tokens(official)
    return bool(wanted and available and set(wanted).issubset(set(available)))


def _number(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text.isdecimal():
        return None
    return str(int(text))


def _number_matches(expected: str, official: Any) -> bool:
    return _number(expected) is not None and _number(expected) == _number(official)


def _field(properties: dict[str, Any], *names: str) -> Any:
    # Joinville exposes qualified names such as gisdb.gisadmin.lotes.iq.
    fields = {str(key).rsplit(".", 1)[-1].casefold(): value for key, value in properties.items()}
    for name in names:
        value = fields.get(name.casefold())
        if value is not None and str(value).strip() not in {"", "-", "—"}:
            return value
    return None


def _float(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "."))
        return number if math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError):
        return None


def _geometry(feature: dict[str, Any]) -> tuple[str | None, float | None, float | None]:
    raw = feature.get("geometry") or {}
    rings = raw.get("rings") if isinstance(raw, dict) else None
    if not isinstance(rings, list) or not rings:
        return None, None, None
    valid_rings = []
    for ring in rings:
        if not isinstance(ring, list):
            continue
        points = [
            [float(point[0]), float(point[1])]
            for point in ring
            if isinstance(point, (list, tuple)) and len(point) >= 2
            and all(isinstance(part, (int, float)) for part in point[:2])
            and -180 <= point[0] <= 180 and -90 <= point[1] <= 90
        ]
        if len(points) >= 4:
            valid_rings.append(points)
    if not valid_rings:
        return None, None, None
    first_ring = valid_rings[0]
    center = first_ring[:-1] if first_ring[0] == first_ring[-1] else first_ring
    geojson = json.dumps({"type": "Polygon", "coordinates": valid_rings}, ensure_ascii=False)
    return (
        geojson,
        sum(point[1] for point in center) / len(center),
        sum(point[0] for point in center) / len(center),
    )


def _query(fetch: Fetch, layer: str, where: str, *, geometry: bool) -> list[dict[str, Any]]:
    response = fetch(layer + "/query", {
        "where": where,
        "outFields": "*",
        "returnGeometry": "true" if geometry else "false",
        "outSR": 4326,
        "f": "json",
        "resultRecordCount": MAX_RESULTS,
    })
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        error = payload.get("error") if isinstance(payload, dict) else type(payload).__name__
        raise RuntimeError(f"ArcGIS municipal retornou consulta inválida: {error!r}")
    return [feature for feature in payload["features"] if isinstance(feature, dict)]


def _query_token(address: str) -> str | None:
    tokens = _street_tokens(address)
    # Tokens originate from user input and must never enter SQL unescaped.
    return max(tokens, key=len).upper().replace("'", "''") if tokens else None


def joinville(request: SearchRequest, fetch: Fetch, source_id: str) -> tuple[list[PropertyRecord], dict[str, Any]]:
    number, token = _number(request.number), _query_token(request.address or "")
    diagnostic: dict[str, Any] = {"endpoint": JOINVILLE_LAYER, "query_mode": "exact_municipal_address"}
    if not number or not token:
        diagnostic["result"] = "street_and_numeric_number_required"
        return [], diagnostic
    where = (
        "gisdb.gisadmin.mvw_lote.logradouro LIKE '%" + token + "%' "
        "AND gisdb.gisadmin.mvw_lote.numero = " + number
    )
    candidates = _query(fetch, JOINVILLE_LAYER, where, geometry=True)
    records: list[PropertyRecord] = []
    for feature in candidates:
        props = feature.get("attributes") or {}
        if not isinstance(props, dict):
            continue
        street = _field(props, "logradouro")
        found_number = _field(props, "numero")
        if not _street_matches(request.address or "", street) or not _number_matches(number, found_number):
            continue
        inscription = _field(props, "iq")
        geometry, lat, lon = _geometry(feature)
        block = _field(props, "quadra")
        lot = _field(props, "lote")
        registry = _field(props, "matricula_ri")
        records.append(PropertyRecord(
            property_id=str(_field(props, "objectid", "mslink") or "") or None,
            registry_number=str(registry) if registry is not None else None,
            address=f"{street}, {found_number}",
            city="Joinville", state="SC",
            block=str(block) if block is not None else None,
            lot=str(lot) if lot is not None else None,
            area_m2=_float(_field(props, "area_terreno")),
            latitude=lat, longitude=lon,
            attributes={
                "source": source_id,
                "official_source": "Prefeitura de Joinville — SEFAZ Lotes",
                "service_type": "ArcGIS REST",
                "service_url": JOINVILLE_LAYER,
                "source_properties": props,
                "geometry_geojson": geometry,
                "municipal_registration_number": str(inscription) if inscription is not None else None,
                "iptu_registration_number": str(inscription) if inscription is not None else None,
                "sql": None,
                "sql_status": "not_applicable_sp_sql",
                "iptu_status": "provided_by_layer" if inscription is not None else "not_provided_by_layer",
                "cadastre_match": "exact_address_match",
                "owner_status": "not_requested",
            },
            provenance=(Provenance(
                source_id=source_id, confidence=0.95,
                reference=str(inscription or _field(props, "objectid") or ""),
            ),),
        ))
        if len(records) >= MAX_RESULTS:
            break
    diagnostic.update({
        "candidate_count": len(candidates),
        "exact_match_count": len(records),
        "polygon_count": sum(bool(record.attributes["geometry_geojson"]) for record in records),
        "registration_count": sum(bool(record.attributes["iptu_registration_number"]) for record in records),
        "result": "exact_address_records" if records else "no_exact_address_match",
    })
    return records, diagnostic


def sao_bento(request: SearchRequest, fetch: Fetch, source_id: str) -> tuple[list[PropertyRecord], dict[str, Any]]:
    number, token = _number(request.number), _query_token(request.address or "")
    diagnostic: dict[str, Any] = {
        "endpoint": SAO_BENTO_SERVICE,
        "query_mode": "address_table_joined_by_geolot",
    }
    if not number or not token:
        diagnostic["result"] = "street_and_numeric_number_required"
        return [], diagnostic
    where = "numero = '" + number + "' AND descricao_logradouro LIKE '%" + token + "%'"
    addresses = _query(fetch, SAO_BENTO_SERVICE + "/11", where, geometry=False)
    matched: dict[str, dict[str, Any]] = {}
    for row in addresses:
        props = row.get("attributes") or {}
        if not isinstance(props, dict):
            continue
        if _field(props, "tipo_endereco") not in (1, "1", None):
            continue
        if not _street_matches(request.address or "", _field(props, "descricao_logradouro")):
            continue
        if not _number_matches(number, _field(props, "numero")):
            continue
        geolot = _field(props, "geolot")
        if geolot is not None:
            matched.setdefault(str(geolot), props)
        if len(matched) >= MAX_RESULTS:
            break
    diagnostic["address_candidate_count"] = len(addresses)
    diagnostic["exact_address_geolots"] = len(matched)
    if not matched:
        diagnostic["result"] = "no_exact_address_match"
        return [], diagnostic

    # Restrict all follow-up requests to geolot keys returned by exact
    # municipal address rows. No unrelated nearby lots or taxpayer records.
    quoted = ", ".join("'" + key.replace("'", "''") + "'" for key in matched)
    where_lots = "geolot IN (" + quoted + ")"
    lots = _query(fetch, SAO_BENTO_SERVICE + "/0", where_lots, geometry=True)
    cadastres = _query(
        fetch, SAO_BENTO_SERVICE + "/14",
        where_lots + " AND tipo_cadastro = 1", geometry=False,
    )
    by_lot = {
        str(_field(feature.get("attributes") or {}, "geolot")): feature
        for feature in lots
        if isinstance(feature.get("attributes"), dict)
        and _field(feature["attributes"], "geolot") is not None
    }
    registrations: dict[str, set[str]] = {}
    areas: dict[str, float] = {}
    for row in cadastres:
        props = row.get("attributes") or {}
        if not isinstance(props, dict) or _field(props, "tipo_cadastro") not in (1, "1"):
            continue
        key = _field(props, "geolot")
        if key is None:
            continue
        key = str(key)
        inscription = _field(props, "inscricao_imobiliaria")
        if inscription is not None:
            registrations.setdefault(key, set()).add(str(inscription))
        area = _float(_field(props, "area_terreno"))
        if area is not None:
            areas[key] = area

    results: list[PropertyRecord] = []
    for geolot, address_row in matched.items():
        feature = by_lot.get(geolot, {})
        lot_row = feature.get("attributes") or {}
        geometry, lat, lon = _geometry(feature)
        values = registrations.get(geolot, set())
        inscription = next(iter(values)) if len(values) == 1 else None
        block = _field(address_row, "quadra") or _field(lot_row, "quadra")
        lot = _field(address_row, "lote") or _field(lot_row, "lote")
        street = _field(address_row, "descricao_logradouro")
        results.append(PropertyRecord(
            property_id=str(_field(lot_row, "objectid") or geolot),
            address=f"{street}, {number}",
            city="São Bento do Sul", state="SC",
            block=str(block) if block is not None else None,
            lot=str(lot) if lot is not None else None,
            area_m2=areas.get(geolot) or _float(_field(lot_row, "area_sig_")),
            latitude=lat, longitude=lon,
            attributes={
                "source": source_id,
                "official_source": "Prefeitura de São Bento do Sul — Geobensul",
                "service_type": "ArcGIS REST",
                "service_url": SAO_BENTO_SERVICE + "/0",
                "address_table_url": SAO_BENTO_SERVICE + "/11",
                "registration_table_url": SAO_BENTO_SERVICE + "/14",
                "source_properties": address_row,
                "geometry_geojson": geometry,
                "parcel_identifier": geolot,
                "municipal_registration_number": inscription,
                "iptu_registration_number": inscription,
                "sql": None,
                "sql_status": "not_applicable_sp_sql",
                "iptu_status": "provided_by_table" if inscription else "not_provided_or_ambiguous",
                "registration_ambiguity_count": len(values),
                "cadastre_match": "exact_address_match",
                "owner_status": "not_requested",
            },
            provenance=(Provenance(
                source_id=source_id, confidence=0.95, reference=geolot,
            ),),
        ))
    diagnostic.update({
        "exact_match_count": len(results),
        "polygon_count": sum(bool(record.attributes["geometry_geojson"]) for record in results),
        "registration_count": sum(bool(record.attributes["iptu_registration_number"]) for record in results),
        "result": "exact_address_records" if results else "no_exact_address_match",
    })
    return results, diagnostic
