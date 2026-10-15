from imobhunter.application.address import normalize_request
from imobhunter.domain.models import SearchRequest


def test_normalize_request_is_deterministic() -> None:
    request = SearchRequest(
        address="Rua São José, 42.",
        city="São Paulo",
        state="sp",
    )
    result = normalize_request(request)
    assert result.normalized == "RUA SAO JOSE 42"
    assert result.city == "SAO PAULO"
    assert result.state == "SP"


def test_normalize_request_rejects_invalid_state() -> None:
    request = SearchRequest(address="Rua A", state="XX")
    try:
        normalize_request(request)
    except ValueError as exc:
        assert "invalid Brazilian state" in str(exc)
    else:
        raise AssertionError("invalid state was accepted")


def test_geosampa_street_type_and_name_are_separated() -> None:
    result = normalize_request(
        SearchRequest(address="Rua Pamplona", number="1578", city="São Paulo", state="SP")
    )
    assert result.street_type == "R"
    assert result.street_title is None
    assert result.street_name == "PAMPLONA"
    assert result.number == "1578"


def test_geosampa_accepts_abbreviated_street_type() -> None:
    result = normalize_request(
        SearchRequest(address="R Pamplona", number="1578", city="São Paulo", state="SP")
    )
    assert result.street_type == "R"
    assert result.street_name == "PAMPLONA"


def test_geosampa_separates_street_title() -> None:
    result = normalize_request(
        SearchRequest(address="Avenida Padre Anchieta", number="100", state="SP")
    )
    assert result.street_type == "AV"
    assert result.street_title == "PADRE"
    assert result.street_name == "ANCHIETA"


def test_geosampa_preserves_untyped_street_name() -> None:
    result = normalize_request(SearchRequest(address="PAMPLONA", number="1578"))
    assert result.street_type is None
    assert result.street_title is None
    assert result.street_name == "PAMPLONA"


def test_geosampa_extracts_house_number_from_combined_address() -> None:
    result = normalize_request(
        SearchRequest(address="Rua Pamplona, 1578", city="São Paulo", state="SP")
    )
    assert result.street_type == "R"
    assert result.street_name == "PAMPLONA"
    assert result.number == "1578"
    assert result.normalized == "RUA PAMPLONA 1578"


def test_geosampa_extracts_number_marker_and_suffix() -> None:
    result = normalize_request(SearchRequest(address="Av Paulista nº 1578-A"))
    assert result.street_type == "AV"
    assert result.street_name == "PAULISTA"
    assert result.number == "1578-A"


def test_explicit_house_number_takes_precedence_over_inline_number() -> None:
    result = normalize_request(
        SearchRequest(address="Rua Pamplona, 1578", number="1600")
    )
    assert result.street_name == "PAMPLONA 1578"
    assert result.number == "1600"
