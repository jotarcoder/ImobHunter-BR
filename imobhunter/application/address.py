import re
import unicodedata

from imobhunter.domain.models import NormalizedAddress, SearchRequest

_SPACES = re.compile(r"\s+")
_PUNCT = re.compile(r"[,.;:]+")
_VALID_UFS = frozenset(
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
)

def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = _PUNCT.sub(" ", value.upper())
    return _SPACES.sub(" ", value).strip() or None

def normalize_request(request: SearchRequest) -> NormalizedAddress:
    address = normalize_text(request.address) or ""
    number = normalize_text(request.number)
    state = normalize_text(request.state)
    if state and state not in _VALID_UFS:
        raise ValueError(f"invalid Brazilian state: {state}")
    city = normalize_text(request.city)
    normalized = " ".join(part for part in (address, number) if part)
    return NormalizedAddress(
        original=request.address or "",
        normalized=normalized,
        number=number,
        city=city,
        state=state,
    )
