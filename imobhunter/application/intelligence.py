from dataclasses import dataclass
from imobhunter.domain.models import PropertyRecord, Provenance


SOURCE_PRIORITY = {
    "sinter_cib": 100,
    "geosampa": 95,
    "ibge_cnefe": 90,
    "municipal": 90,
    "sncr": 90,
    "sicar": 85,
    "sigef": 85,
    "cnir": 85,
    "cnpj": 75,
    "receita_cnpj": 75,
    "osm": 50,
}


@dataclass(frozen=True)
class PropertyFact:
    field: str
    value: object
    provenance: Provenance
    source_priority: int


@dataclass(frozen=True)
class PropertyConflict:
    field: str
    values: tuple[object, ...]


@dataclass(frozen=True)
class PropertyDossier:
    identity: str
    facts: tuple[PropertyFact, ...]
    conflicts: tuple[PropertyConflict, ...]
    score: float
    score_reasons: tuple[str, ...]


def _priority(source_id: str) -> int:
    return SOURCE_PRIORITY.get(source_id, 40)


def _fields(record: PropertyRecord) -> dict[str, object]:
    # Keep cadastral geometry in the map, not as a huge text field in the
    # dossier. Preserve normalized adapter attributes and flatten every raw
    # source property into its own fact so the user can inspect the complete
    # GeoSampa response without losing fields unknown to the current UI.
    attributes = {
        key: value
        for key, value in record.attributes.items()
        if key not in {"geometry_geojson", "source_attributes", "source_attribute_names"}
    }
    source_attributes = record.attributes.get("source_attributes")
    source_id = str(record.attributes.get("source") or "source")
    raw_facts = (
        {
            f"source_attribute:{source_id}:{key}": value
            for key, value in source_attributes.items()
            if value not in (None, "")
        }
        if isinstance(source_attributes, dict)
        else {}
    )
    return {
        "address": record.address,
        "registry_number": record.registry_number,
        "cib": record.cib,
        "property_id": record.property_id,
        "owner_name": record.owner_name,
        "owner_document": record.owner_document,
        "block": record.block,
        "lot": record.lot,
        "area_m2": record.area_m2,
        "latitude": record.latitude,
        "longitude": record.longitude,
        **{f"attribute:{key}": value for key, value in attributes.items()},
        **raw_facts,
    }


def build_dossier(
    identity: str, records: tuple[PropertyRecord, ...]
) -> PropertyDossier:
    candidates: dict[str, list[PropertyFact]] = {}
    for record in records:
        for field, value in _fields(record).items():
            if value is None or value == "":
                continue
            provenance = max(
                record.provenance,
                key=lambda item: (item.confidence, _priority(item.source_id)),
                default=Provenance("unknown"),
            )
            candidates.setdefault(field, []).append(
                PropertyFact(field, value, provenance, _priority(provenance.source_id))
            )

    chosen: list[PropertyFact] = []
    conflicts: list[PropertyConflict] = []
    for field, facts in candidates.items():
        ranked = sorted(
            facts,
            key=lambda fact: (
                fact.provenance.confidence,
                fact.source_priority,
                fact.provenance.retrieved_at,
            ),
            reverse=True,
        )
        chosen.append(ranked[0])
        values: list[object] = []
        for fact in ranked:
            if fact.value not in values:
                values.append(fact.value)
        if len(values) > 1:
            conflicts.append(PropertyConflict(field, tuple(values)))

    score, reasons = opportunity_score(tuple(chosen), tuple(conflicts))
    return PropertyDossier(
        identity=identity,
        facts=tuple(sorted(chosen, key=lambda fact: fact.field)),
        conflicts=tuple(sorted(conflicts, key=lambda conflict: conflict.field)),
        score=score,
        score_reasons=reasons,
    )


def opportunity_score(
    facts: tuple[PropertyFact, ...],
    conflicts: tuple[PropertyConflict, ...],
) -> tuple[float, tuple[str, ...]]:
    fields = {fact.field for fact in facts}
    score = 0.0
    reasons: list[str] = []

    checks = (
        ("cib", 25.0, "CIB identificado"),
        ("owner_name", 5.0, "Titular identificado"),
        ("block", 20.0, "Quadra identificada"),
        ("lot", 20.0, "Lote identificado"),
        ("area_m2", 15.0, "Área identificada"),
        ("latitude", 7.5, "Latitude identificada"),
        ("longitude", 7.5, "Longitude identificada"),
        ("address", 10.0, "Endereço identificado"),
    )
    for field, points, reason in checks:
        if field in fields:
            score += points
            reasons.append(reason)

    penalty = min(20.0, sum(2.5 for _ in conflicts))
    if penalty:
        score -= penalty
        reasons.append(f"{len(conflicts)} conflito(s) reduzem a confiança")

    return max(0.0, min(100.0, score)), tuple(reasons)
