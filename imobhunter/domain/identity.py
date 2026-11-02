import hashlib
import re
import unicodedata

from imobhunter.domain.models import PropertyRecord


def canonical_text(value: object) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", value.upper()).strip()


def canonical_cib(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _explicit_door_number(record: PropertyRecord) -> str:
    """Only use a postal address as an identity when its number is explicit.

    A municipal parcel layer often exposes just the street name. Merging by
    that string collapses different fiscal lots into one fictitious property.
    """
    door = record.attributes.get("door_number") or record.attributes.get("house_number")
    if door not in (None, ""):
        return canonical_text(door)
    address = str(record.address or "")
    match = re.search(r",\s*(?:N[º°.]\s*)?(\d+[A-Za-z]?)\s*$", address, re.I)
    return canonical_text(match.group(1)) if match else ""


def identity_keys(record: PropertyRecord) -> frozenset[str]:
    keys: set[str] = set()
    if record.cib:
        keys.add(f"cib:{canonical_cib(record.cib)}")
    if record.property_id:
        source_id = max(record.provenance, key=lambda item: item.confidence).source_id if record.provenance else "unknown"
        keys.add(f"property:{canonical_text(source_id)}:{canonical_text(record.property_id)}")
    if record.block and record.lot and record.city and record.state:
        keys.add(
            f"parcel:{canonical_text(record.state)}:{canonical_text(record.city)}:"
            f"{canonical_text(record.block)}:{canonical_text(record.lot)}"
        )
    # Address is a fallback ONLY when a source offers no fiscal identifier.
    # Do not share an address key with a cadastral record: geocoded points and
    # street-level records must not merge distinct neighboring parcels.
    if not keys and record.address and record.city and record.state:
        door = _explicit_door_number(record)
        if door:
            keys.add(
                f"address:{canonical_text(record.state)}:"
                f"{canonical_text(record.city)}:{canonical_text(record.address)}:{door}"
            )
    if record.latitude is not None and record.longitude is not None and not keys:
        # Coordinate-only matches are not proof of cadastral identity. Keep
        # different sources separate unless a stronger identifier matches.
        source = (
            max(record.provenance, key=lambda item: item.confidence).source_id
            if record.provenance else str(record.attributes.get("source") or "unknown")
        )
        keys.add(
            f"coord:{canonical_text(source)}:"
            f"{record.latitude:.6f}:{record.longitude:.6f}"
        )
    return frozenset(keys)


def stable_identity(record: PropertyRecord) -> str:
    keys = identity_keys(record)
    if not keys:
        raise ValueError("record has no identity keys")
    return hashlib.sha256("|".join(sorted(keys)).encode()).hexdigest()
