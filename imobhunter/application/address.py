import re
import unicodedata

from imobhunter.domain.models import NormalizedAddress, SearchRequest

_SPACES = re.compile(r"\s+")
_PUNCT = re.compile(r"[,.;:]+")
# Accept a house number typed at the end of the address field, e.g. "Rua X, 42",
# "Av X nº 42" or "Rua X 42-A".
_TRAILING_HOUSE_NUMBER = re.compile(
    r"\s+(?:N(?:\s*O|[º°.]|UMERO)?\s*)?(\d+(?:[A-Z]|[-/][A-Z0-9]+)?)$"
)
_VALID_UFS = frozenset(
    [
        "AC",
        "AL",
        "AP",
        "AM",
        "BA",
        "CE",
        "DF",
        "ES",
        "GO",
        "MA",
        "MT",
        "MS",
        "MG",
        "PA",
        "PB",
        "PR",
        "PE",
        "PI",
        "RJ",
        "RN",
        "RS",
        "RO",
        "RR",
        "SC",
        "SP",
        "SE",
        "TO",
    ]
)

# GeoSampa separates the street type from the street name. These aliases keep
# user input flexible while preserving the source's expected abbreviations.
_STREET_TYPES = {
    "R": "R",
    "RUA": "R",
    "AV": "AV",
    "AVEN": "AV",
    "AVENIDA": "AV",
    "AL": "AL",
    "ALAM": "AL",
    "ALAMEDA": "AL",
    "TV": "TV",
    "TRAV": "TV",
    "TRAVESSA": "TV",
    "VL": "VL",
    "VIELA": "VL",
    "EST": "EST",
    "ESTR": "EST",
    "ESTRADA": "EST",
    "ROD": "ROD",
    "RODOVIA": "ROD",
    "PCA": "PCA",
    "PC": "PCA",
    "PRACA": "PCA",
    "LGO": "LGO",
    "LARGO": "LGO",
    "BECO": "BC",
    "BC": "BC",
}

# Common titles are optional in GeoSampa and belong in their own field.
_STREET_TITLES = {
    "SANTO",
    "SANTA",
    "SAO",
    "PADRE",
    "PROFESSOR",
    "PROF",
    "DOUTOR",
    "DR",
    "ENGENHEIRO",
    "ENG",
    "GENERAL",
    "GEN",
    "MARECHAL",
    "MAJ",
    "MAJOR",
    "DESEMBARGADOR",
    "DESEMB",
    "PRESIDENTE",
    "PRES",
    "COMENDADOR",
    "CAPITAO",
    "CAP",
    "CORONEL",
    "CEL",
}


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = _PUNCT.sub(" ", value)
    value = _SPACES.sub(" ", value).strip().upper()
    return value or None


def _parse_street(address: str | None) -> tuple[str | None, str | None, str | None]:
    normalized = normalize_text(address)
    if not normalized:
        return None, None, None

    tokens = normalized.split()
    street_type = _STREET_TYPES.get(tokens[0])
    if street_type is None:
        return None, None, normalized

    tokens = tokens[1:]
    title = None
    if tokens and tokens[0] in _STREET_TITLES:
        title = tokens.pop(0)

    street_name = " ".join(tokens) or None
    return street_type, title, street_name


def normalize_request(request: SearchRequest) -> NormalizedAddress:
    address = normalize_text(request.address) or ""
    number = normalize_text(request.number)
    # The desktop form may send "Rua Pamplona, 1578" as one field instead of
    # separating the number. Split it before deriving the street name; otherwise
    # the WFS filter incorrectly searches for a street literally named
    # "PAMPLONA 1578". A separately supplied number takes precedence.
    if address:
        match = _TRAILING_HOUSE_NUMBER.search(address)
        if match:
            if not number:
                number = match.group(1)
            address = address[: match.start()].strip()

    state = normalize_text(request.state)
    if state and state not in _VALID_UFS:
        raise ValueError(f"invalid Brazilian state: {state}")
    city = normalize_text(request.city)

    street_type, street_title, street_name = _parse_street(address)
    normalized = " ".join(part for part in (address, number) if part)
    return NormalizedAddress(
        original=request.address or "",
        normalized=normalized,
        number=number,
        city=city,
        state=state,
        street_type=street_type,
        street_title=street_title,
        street_name=street_name,
    )
