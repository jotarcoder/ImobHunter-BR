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

def identity_keys(record: PropertyRecord) -> frozenset[str]:
    keys: set[str] = set()
    if record.cib:
        keys.add(f"cib:{canonical_cib(record.cib)}")
    if record.property_id:
        keys.add(f"property:{canonical_text(record.property_id)}")
    if record.block and record.lot and record.city and record.state:
        keys.add(
            f"parcel:{canonical_text(record.state)}:{canonical_text(record.city)}:"
            f"{canonical_text(record.block)}:{canonical_text(record.lot)}"
        )
    if record.address and record.city and record.state:
        keys.add(
            f"address:{canonical_text(record.address)}:"
            f"{canonical_text(record.city)}:{canonical_text(record.state)}"
        )
    if record.latitude is not None and record.longitude is not None:
        keys.add(f"coord:{record.latitude:.6f}:{record.longitude:.6f}")
    return frozenset(keys)

def stable_identity(record: PropertyRecord) -> str:
    keys = identity_keys(record)
    if not keys:
        raise ValueError("record has no identity keys")
    return hashlib.sha256("|".join(sorted(keys)).encode()).hexdigest()
