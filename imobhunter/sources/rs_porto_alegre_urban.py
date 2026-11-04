"""Join public DMWEB tables to parcels using ONLY the published id_lotes key.

NUMBLOCO from the separate SMF MapServer/98 is a different identifier;
it must never be joined to DMWEB id_lotes, or labelled as an IPTU SQL.
"""
from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Callable

import httpx

from imobhunter.domain.models import PropertyRecord

BASE = (
    "https://gis-smamus.portoalegre.rs.gov.br/server/rest/services/"
    "01_PUBLICACOES/dmweb_lotes_fiscais/MapServer"
)
TABLE_FIELDS = {
    3: "id_lotes,bairro,setor,quarteirao,sub_atividade,sub_densidade,sub_indice,sub_volumetria",
    4: "id_lotes,parcel_area,zone_percent,concat_zone_percent,zoned_parcel_percent",
    5: "id_lotes,json_front",
}
MAX_IDS = 20
MAX_TABLE_RESULTS = 500


def _id(value: Any) -> int | None:
    text = str(value or "")
    return int(text) if text.isdecimal() and 0 < int(text) < 2_147_483_648 else None


def _number(value: Any) -> float | None:
    try:
        n = float(value)
        return n if math.isfinite(n) and n >= 0 else None
    except (TypeError, ValueError):
        return None


def enrich_dmweb_lots(
    records: list[PropertyRecord],
    get: Callable[[str, dict[str, Any]], Any],
) -> tuple[list[PropertyRecord], dict[str, Any]]:
    """Add bounded public planning context to DMWEB parcels; fail soft per table."""
    indices: dict[int, list[int]] = {}
    for index, record in enumerate(records):
        if record.attributes.get("service_url") != BASE + "/0":
            continue
        parcel_id = _id(record.attributes.get("parcel_identifier"))
        if parcel_id is not None:
            indices.setdefault(parcel_id, []).append(index)
    ids = list(indices)[:MAX_IDS]
    diag: dict[str, Any] = {"linked_by": "dmweb_id_lotes_only", "requested_parcel_ids": len(ids)}
    if not ids:
        return records, diag
    rows_by_table: dict[int, dict[int, dict[str, Any]]] = {}
    for layer, fields in TABLE_FIELDS.items():
        try:
            response = get(BASE + f"/{layer}/query", {
                "where": "id_lotes IN (" + ",".join(str(pid) for pid in ids) + ")",
                "outFields": fields, "returnGeometry": "false", "f": "json",
                "resultRecordCount": MAX_TABLE_RESULTS,
            })
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("features"), list) or payload.get("error"):
                raise ValueError("Tabela DMWEB indisponível ou inválida")
            index_rows: dict[int, dict[str, Any]] = {}
            for feature in payload["features"][:MAX_TABLE_RESULTS]:
                attrs = feature.get("attributes") if isinstance(feature, dict) else None
                if not isinstance(attrs, dict):
                    continue
                ident = _id(attrs.get("id_lotes"))
                if ident is not None and ident in indices:
                    index_rows[ident] = attrs
            rows_by_table[layer] = index_rows
            diag[f"table_{layer}_matches"] = len(index_rows)
        except (httpx.HTTPError, ValueError, TypeError, OSError, RuntimeError, KeyError) as exc:
            diag[f"table_{layer}_unavailable"] = type(exc).__name__
    updated = list(records)
    for parcel_id, positions in indices.items():
        planning = rows_by_table.get(3, {}).get(parcel_id, {})
        zoning = rows_by_table.get(4, {}).get(parcel_id, {})
        frontage = rows_by_table.get(5, {}).get(parcel_id, {})
        if not (planning or zoning or frontage):
            continue
        for position in positions:
            rec = updated[position]
            attrs = dict(rec.attributes)
            attrs["urban_planning_dmweb"] = {
                key: planning.get(key) for key in
                ("bairro", "setor", "quarteirao", "sub_atividade", "sub_densidade", "sub_indice", "sub_volumetria")
                if planning.get(key) is not None
            }
            attrs["zoning_dmweb"] = {
                "zone_percent": str(zoning.get("zone_percent") or "")[:300],
                "concat_zone_percent": str(zoning.get("concat_zone_percent") or "")[:300],
                "zoned_parcel_percent": _number(zoning.get("zoned_parcel_percent")),
            } if zoning else {}
            attrs["frontage_dmweb_available"] = bool(frontage.get("json_front"))
            attrs["related_tables_join"] = "id_lotes (somente DMWEB, não SMF/NUMBLOCO)"
            area = _number(zoning.get("parcel_area")) if zoning else None
            updated[position] = replace(
                rec, attributes=attrs,
                area_m2=rec.area_m2 if rec.area_m2 is not None else area,
            )
    return updated, diag
