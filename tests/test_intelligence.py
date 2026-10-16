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



def test_dossier_flattens_raw_source_attributes_without_embedding_geometry() -> None:
    record = PropertyRecord(
        address="Rua Pamplona",
        block="020",
        lot="0030",
        area_m2=420,
        attributes={
            "source": "geosampa",
            "geometry_geojson": '{"type":"Polygon","coordinates":[]}',
            "source_attribute_names": ["cd_numero_porta", "nm_logradouro_completo"],
            "source_attributes": {
                "cd_numero_porta": "1578",
                "nm_logradouro_completo": "R PAMPLONA",
                "field_not_mapped_yet": "preserved value",
            },
            "door_number": "1578",
        },
        provenance=[provenance("geosampa", 0.95)],
    )

    dossier = build_dossier("property-1", (record,))
    facts = {fact.field: fact.value for fact in dossier.facts}

    assert facts["source_attribute:geosampa:cd_numero_porta"] == "1578"
    assert facts["source_attribute:geosampa:nm_logradouro_completo"] == "R PAMPLONA"
    assert facts["source_attribute:geosampa:field_not_mapped_yet"] == "preserved value"
    assert facts["attribute:door_number"] == "1578"
    assert "attribute:geometry_geojson" not in facts
    assert "attribute:source_attributes" not in facts
    assert "attribute:source_attribute_names" not in facts
