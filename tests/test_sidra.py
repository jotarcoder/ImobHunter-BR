import httpx
import pytest

from imobhunter.application.sidra import (
    SIDRA_BASE_URL,
    fetch_population_estimate,
    search_municipalities,
)


def _client(payload, *, status_code=200):
    def handler(request):
        return httpx.Response(status_code, json=payload, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_population_estimate_parses_sidra_compact_fields_and_metadata():
    payload = [
        {"NC": "3", "NN": "Município", "MC": "3550308", "MN": "São Paulo",
         "D1C": "2026", "D1N": "2026", "V": "11895893"},
        {"NC": "3", "NN": "Município", "MC": "3550308", "MN": "São Paulo",
         "D1C": "2026", "D1N": "2026", "V": "11895893"},
    ]
    with _client(payload) as client:
        result = fetch_population_estimate("3550308", client=client)
    assert result["municipality"] == "São Paulo"
    assert result["period"] == "2026"
    assert result["population"] == 11895893
    assert result["source_url"] == "https://sidra.ibge.gov.br/tabela/6579"
    assert result["api_url"] == f"{SIDRA_BASE_URL}/t/6579/n6/3550308/v/9324/p/last%201"


@pytest.mark.parametrize("code", ["", "123", "35503080", "35A0308", "SP3550308"])
def test_population_estimate_rejects_invalid_municipality_codes(code):
    with pytest.raises(ValueError):
        fetch_population_estimate(code, client=_client([]))


def test_population_estimate_rejects_missing_or_invalid_rows():
    for payload in ([], [{"MN": "São Paulo"}], [{}, {"MN": "São Paulo", "D1N": "2026", "V": "-"}]):
        with _client(payload) as client:
            with pytest.raises(RuntimeError):
                fetch_population_estimate("3550308", client=client)


def test_population_estimate_reports_http_errors():
    with _client({"message": "unavailable"}, status_code=503) as client:
        with pytest.raises(RuntimeError, match="IBGE/SIDRA"):
            fetch_population_estimate("3550308", client=client)


def test_search_municipalities_maps_code_name_and_state():
    payload = [{
        "id": 3550308,
        "nome": "São Paulo",
        "microrregiao": {"mesorregiao": {"UF": {"sigla": "SP"}}},
    }]
    with _client(payload) as client:
        results = search_municipalities("São Paulo", client=client)
    assert results == [{"code": "3550308", "name": "São Paulo", "state": "SP"}]


def test_search_municipalities_rejects_short_query():
    with pytest.raises(ValueError):
        search_municipalities("A", client=_client([]))


def test_search_municipalities_checks_response_shape():
    with _client({"error": "bad response"}) as client:
        with pytest.raises(RuntimeError, match="resposta inválida"):
            search_municipalities("São Paulo", client=client)
