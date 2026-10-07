from imobhunter.application.reconcile import reconcile
from imobhunter.domain.models import PropertyRecord

def test_same_cib_merges_records_with_different_property_ids():
    first = PropertyRecord(property_id="municipal-1", cib="ABC1234-5")
    second = PropertyRecord(property_id="municipal-2", cib="ABC1234-5")
    clusters = reconcile((first, second))
    assert len(clusters) == 1
    assert len(clusters[0].records) == 2
