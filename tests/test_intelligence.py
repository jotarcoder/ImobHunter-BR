from datetime import datetime, timezone

from imobhunter.application.intelligence import build_dossier
from imobhunter.domain.models import PropertyRecord, Provenance

def provenance(source_id, confidence):
    return Provenance(source_id, datetime.now(timezone.utc), confidence)

def test_dossier_prefers_high_confidence_and_keeps_conflict():
    first = PropertyRecord(
        cib="ABC1234-5",
        address="Rua A",
        area_m2=100,
        provenance=[provenance("osm", 0.60)],
    )
    second = PropertyRecord(
        cib="ABC1234-5",
        address="Rua A",
        area_m2=105,
        provenance=[provenance("sinter", 0.95)],
    )

    dossier = build_dossier("property-1", (first, second))
    area = next(fact for fact in dossier.facts if fact.field == "area_m2")

    assert area.value == 105
    assert area.provenance.source_id == "sinter"
    assert any(conflict.field == "area_m2" for conflict in dossier.conflicts)
    assert 0 <= dossier.score <= 100
