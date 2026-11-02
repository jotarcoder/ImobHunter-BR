"""Regressions: neighboring cadastral parcels must never share one dossier."""
from imobhunter.application.reconcile import reconcile
from imobhunter.domain.identity import identity_keys
from imobhunter.domain.models import PropertyRecord, Provenance


def parcel(lot: str, source: str = "geosampa") -> PropertyRecord:
    return PropertyRecord(
        property_id=f"010.020.{lot}-1",
        address="R PAMPLONA",
        city="São Paulo",
        state="SP",
        block="020",
        lot=lot,
        latitude=-23.570,
        longitude=-46.650,
        attributes={"door_number": "1578" if lot == "0030" else "1580"},
        provenance=(Provenance(source, confidence=0.95),),
    )


def test_neighbor_parcels_on_the_same_street_remain_separate() -> None:
    a, b = parcel("0030"), parcel("0031")
    clusters = reconcile((a, b))
    assert len(clusters) == 2
    assert all(len(group.records) == 1 for group in clusters)
    assert not identity_keys(a).intersection(identity_keys(b))


def test_same_official_parcel_from_two_sources_is_reconciled() -> None:
    left = parcel("0030")
    right = PropertyRecord(
        property_id="different-source-id",
        address="R PAMPLONA",
        city="São Paulo",
        state="SP",
        block="020",
        lot="0030",
        provenance=(Provenance("municipal_iptu", confidence=0.8),),
    )
    clusters = reconcile((left, right))
    assert len(clusters) == 1
    assert len(clusters[0].records) == 2


def test_plain_street_is_never_a_unique_property_identity() -> None:
    first = PropertyRecord(address="R PAMPLONA", city="São Paulo", state="SP")
    second = PropertyRecord(address="R PAMPLONA", city="São Paulo", state="SP")
    assert not identity_keys(first)
    clusters = reconcile((first, second))
    assert len(clusters) == 2
    assert clusters[0].identity != clusters[1].identity


def test_numbered_address_without_fiscal_identifiers_is_safe_fallback() -> None:
    first = PropertyRecord(address="Rua das Flores, 100", city="São Paulo", state="SP")
    same = PropertyRecord(address="Rua das Flores, 100", city="São Paulo", state="SP")
    neighbor = PropertyRecord(address="Rua das Flores, 102", city="São Paulo", state="SP")
    assert len(reconcile((first, same, neighbor))) == 2


def test_postal_address_never_overrides_different_fiscal_parcels() -> None:
    first = PropertyRecord(
        property_id="fiscal-A",
        address="Rua das Flores, 100",
        city="São Paulo",
        state="SP",
        block="01",
        lot="001",
    )
    second = PropertyRecord(
        property_id="fiscal-B",
        address="Rua das Flores, 100",
        city="São Paulo",
        state="SP",
        block="01",
        lot="002",
    )
    assert len(reconcile((first, second))) == 2


def test_coordinates_only_not_shared_across_sources() -> None:
    first = PropertyRecord(
        latitude=-23.5, longitude=-46.6,
        provenance=(Provenance("source_a"),),
    )
    second = PropertyRecord(
        latitude=-23.5, longitude=-46.6,
        provenance=(Provenance("source_b"),),
    )
    assert len(reconcile((first, second))) == 2
