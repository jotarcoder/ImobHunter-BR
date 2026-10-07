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
    return {
        "address": record.address,
        "city": record.city,
        "state": record.state,
        "postal_code": record.postal_code,
        "block": record.block,
        "lot": record.lot,
        "cib": record.cib,
        "area_m2": record.area_m2,
        "latitude": record.latitude,
        "longitude": record.longitude,
        **{f"attribute:{key}": value for key, value in record.attributes.items()},
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
    score = 0
    reasons: list[str] = []
    fields = {fact.field for fact in facts}

    if "cib" in fields:
        score += 25
        reasons.append("identificador cadastral nacional presente")
    if "block" in fields and "lot" in fields:
        score += 20
        reasons.append("quadra e lote identificados")
    if "area_m2" in fields:
        score += 15
        reasons.append("área do terreno disponível")
    if "latitude" in fields and "longitude" in fields:
        score += 15
        reasons.append("localização geográfica resolvida")
    if "address" in fields:
        score += 10
        reasons.append("endereço identificado")
    if conflicts:
        penalty = min(20, len(conflicts) * 5)
        score -= penalty
        reasons.append(f"{len(conflicts)} conflito(s) entre fontes")

    return max(0, min(100, float(score))), tuple(reasons)
