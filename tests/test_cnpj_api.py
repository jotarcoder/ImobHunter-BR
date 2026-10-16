from __future__ import annotations

import json

from imobhunter.domain.models import SearchRequest
from imobhunter.sources.cnpj import CNPJAdapter
from imobhunter.sources.cnpj_api import CNPJApiClient


def test_conectagov_cnpj_lookup_uses_token_and_three_services(monkeypatch) -> None:
    calls: list[tuple[str, str, dict]] = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self.payload

    def fake_post(url, *, data, auth, headers, timeout):
        calls.append(("POST", url, {"data": data, "auth": auth, "timeout": timeout}))
        assert data == {"grant_type": "client_credentials"}
        assert auth == ("client-id", "client-secret")
        return FakeResponse({"access_token": "test-access-token", "expires_in": 3600})

    def fake_get(url, *, headers, timeout):
        calls.append(("GET", url, {"headers": headers, "timeout": timeout}))
        assert headers["Authorization"] == "Bearer test-access-token"
        assert headers["x-cpf-usuario"] == "12345678901"
        return FakeResponse({"service": url.rsplit("/", 2)[-2]})

    monkeypatch.setattr("imobhunter.sources.cnpj_api.httpx.post", fake_post)
    monkeypatch.setattr("imobhunter.sources.cnpj_api.httpx.get", fake_get)
    client = CNPJApiClient(
        "client-id",
        "client-secret",
        "12345678901",
        endpoints={
            "basica": "https://api.test/basica",
            "empresa": "https://api.test/empresa",
            "qsa": "https://api.test/qsa",
        },
    )

    result = client.lookup("12.345.678/0001-90")

    assert set(result) == {"basica", "empresa", "qsa"}
    assert len([call for call in calls if call[0] == "GET"]) == 3
    assert calls[1][1] == "https://api.test/basica/12345678000190"


def test_conectagov_token_is_reused(monkeypatch) -> None:
    posts = 0

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"access_token": "token", "expires_in": 3600}

    def fake_post(*args, **kwargs):
        nonlocal posts
        posts += 1
        return FakeResponse()

    monkeypatch.setattr("imobhunter.sources.cnpj_api.httpx.post", fake_post)
    client = CNPJApiClient("id", "secret", "12345678901")
    assert client._token() == "token"
    assert client._token() == "token"
    assert posts == 1


def test_cnpj_api_requires_a_valid_cnpj() -> None:
    client = CNPJApiClient("id", "secret", "12345678901")
    try:
        client.lookup("123")
    except ValueError as exc:
        assert "14 dígitos" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_local_cnpj_result_survives_remote_api_failure(tmp_path, monkeypatch) -> None:
    path = tmp_path / "cnpj.json"
    path.write_text(
        json.dumps(
            {
                "estabelecimentos": [
                    {
                        "cnpj": "12.345.678/0001-90",
                        "razao_social": "Empresa Local",
                        "logradouro": "Rua A",
                        "numero": "10",
                        "municipio": "São Paulo",
                        "uf": "SP",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    class FailingClient:
        def lookup(self, cnpj: str):
            raise RuntimeError("API temporariamente indisponível")

    monkeypatch.setattr(
        "imobhunter.sources.cnpj.CNPJApiClient.from_environment",
        lambda: FailingClient(),
    )
    records = CNPJAdapter(path).search(
        SearchRequest(address="Rua A", number="10", city="São Paulo", state="SP")
    )

    assert len(records) == 1
    assert records[0].owner_name == "Empresa Local"
    assert records[0].attributes["conectagov_api_status"] == "error"
    assert "temporariamente indisponível" in records[0].attributes["conectagov_api_message"]
