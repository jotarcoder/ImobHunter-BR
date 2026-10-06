from imobhunter.domain.models import SearchRequest

def test_search_request():
    request = SearchRequest(address="Rua A", number="10", city="São Paulo", state="SP")
    assert request.number == "10"
