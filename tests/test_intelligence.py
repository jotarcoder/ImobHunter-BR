from datetime import UTC, datetime

from imobhunter.application.intelligence import build_dossier
from imobhunter.domain.models import PropertyRecord, Provenance


def provenance(source_id: str, confidence: float) -> Provenance:
    return Provenance(source_id, datetime.now(UTC), confidence)


def test_dossier_prefers_high_confidence_and_keeps_conflict() -> None:
    first = PropertyRecord(
        cib="ABC1234-5",
        address="Rua A",
        area_m2=100,
        provenance=[provenance("osm", 0.60)],
    )
    second = PropertyRecord(
        registry_number="12345",
        cib="ABC1234-5",
        address="Rua A",
        area_m2=105,
        owner_name="Titular Teste",
        provenance=[provenance("sinter_cib", 0.95)],
    )

    dossier = build_dossier("property-1", (first, second))
    area = next(fact for fact in dossier.facts if fact.field == "area_m2")

    assert area.value == 105
    assert area.provenance.source_id == "sinter_cib"
    owner = next(fact for fact in dossier.facts if fact.field == "owner_name")
    assert owner.value == "Titular Teste"
    assert owner.provenance.source_id == "sinter_cib"
    registry = next(fact for fact in dossier.facts if fact.field == "registry_number")
    assert registry.value == "12345"
    assert any(conflict.field == "area_m2" for conflict in dossier.conflicts)
    assert 0 <= dossier.score <= 100
