from imobhunter.application.address import normalize_request
from imobhunter.domain.models import SearchRequest

def test_normalize_request_is_deterministic():
    result = normalize_request(
        SearchRequest(address="Rua São José,", number=" 42 ", city="São Paulo", state="sp")
    )
    assert result.normalized == "RUA SAO JOSE 42"
    assert result.city == "SAO PAULO"
    assert result.state == "SP"

def test_normalize_request_rejects_invalid_state():
    request = SearchRequest(address="Rua A", state="XX")
    try:
        normalize_request(request)
    except ValueError as exc:
        assert "invalid Brazilian state" in str(exc)
    else:
        raise AssertionError("invalid state was accepted")
