from imobhunter.application.reconcile import reconcile
from imobhunter.domain.models import PropertyRecord


def test_same_cib_merges_records_with_different_property_ids() -> None:
    first = PropertyRecord(property_id="municipal-1", cib="ABC1234-5")
    second = PropertyRecord(property_id="municipal-2", cib="ABC1234-5")

    clusters = reconcile((first, second))

    assert len(clusters) == 1
    assert len(clusters[0].records) == 2


def test_reconcile_does_not_merge_same_property_id_from_different_sources():
    from imobhunter.domain.models import Provenance

    left = PropertyRecord(
        property_id="001",
        address="Rua A 10",
        city="Campinas",
        state="SP",
        provenance=(Provenance("source_a", confidence=0.9),),
    )
    right = PropertyRecord(
        property_id="001",
        address="Rua B 20",
        city="Campinas",
        state="SP",
        provenance=(Provenance("source_b", confidence=0.9),),
    )

    assert len(reconcile((left, right))) == 2
