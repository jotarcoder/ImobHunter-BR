from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from imobhunter.application.search import SearchResult


def _provenance(value: Any) -> dict[str, Any]:
    return {
        "source_id": value.source_id,
        "confidence": value.confidence,
        "retrieved_at": value.retrieved_at,
    }


def search_result_payload(result: SearchResult) -> dict[str, Any]:
    return {
        "normalized_address": result.normalized.normalized,
        "records": [
            {
                "property_id": record.property_id,
                "registry_number": record.registry_number,
                "cib": record.cib,
                "address": record.address,
                "city": record.city,
                "state": record.state,
                "block": record.block,
                "lot": record.lot,
                "area_m2": record.area_m2,
                "latitude": record.latitude,
                "longitude": record.longitude,
                "owner_name": record.owner_name,
                "owner_document": record.owner_document,
                "attributes": record.attributes,
                "provenance": [_provenance(item) for item in record.provenance],
            }
            for record in result.records
        ],
        "dossiers": [
            {
                "identity": dossier.identity,
                "score": dossier.score,
                "score_reasons": list(dossier.score_reasons),
                "facts": [
                    {
                        "field": fact.field,
                        "value": fact.value,
                        "source_priority": fact.source_priority,
                        "provenance": _provenance(fact.provenance),
                    }
                    for fact in dossier.facts
                ],
                "conflicts": [
                    {"field": conflict.field, "values": list(conflict.values)}
                    for conflict in dossier.conflicts
                ],
            }
            for dossier in result.dossiers
        ],
        "sources": [
            {
                "source_id": source.source_id,
                "name": source.name,
                "status": source.status,
                "records_count": source.records_count,
                "message": source.message,
            }
            for source in result.sources
        ],
    }


def export_search_result_json(result: SearchResult, path: str | Path) -> None:
    target = Path(path)
    target.write_text(
        json.dumps(search_result_payload(result), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def export_search_result_csv(result: SearchResult, path: str | Path) -> None:
    target = Path(path)
    with target.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "dossier_identity",
                "confidence_score",
                "field",
                "value",
                "source_id",
                "source_confidence",
                "source_priority",
            ],
        )
        writer.writeheader()
        for dossier in result.dossiers:
            for fact in dossier.facts:
                writer.writerow(
                    {
                        "dossier_identity": dossier.identity,
                        "confidence_score": dossier.score,
                        "field": fact.field,
                        "value": json.dumps(fact.value, ensure_ascii=False, allow_nan=False)
                        if isinstance(fact.value, (dict, list, tuple))
                        else fact.value,
                        "source_id": fact.provenance.source_id,
                        "source_confidence": fact.provenance.confidence,
                        "source_priority": fact.source_priority,
                    }
                )
