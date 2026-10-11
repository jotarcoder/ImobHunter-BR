from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pytest

from imobhunter.application.address_geocoding import (
    CachedAddressGeocoder,
    GeocodingError,
)


def _client(response_body, status_code=200):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == "ImobHunter-BR/0.1 (support@example.com)"
        return httpx.Response(status_code, json=response_body, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_geocoder_saves_result_and_uses_cache(tmp_path: Path):
    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, json=[{
            "lat": "-23.5505", "lon": "-46.6333", "display_name": "São Paulo, Brasil"
        }], request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    geocoder = CachedAddressGeocoder(
        tmp_path / "market.sqlite3",
        "ImobHunter-BR/0.1 (support@example.com)",
        client=client,
    )
    first = geocoder.geocode(" Avenida Paulista, 1000, São Paulo, SP ")
    second = geocoder.geocode("Avenida Paulista, 1000, São Paulo, SP")
    assert first["latitude"] == -23.5505
    assert first["longitude"] == -46.6333
    assert first["cached"] is False
    assert second["cached"] is True
    assert len(calls) == 1
    with sqlite3.connect(tmp_path / "market.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM geocoding_cache").fetchone()[0] == 1
    client.close()


def test_geocoder_reports_no_results(tmp_path: Path):
    geocoder = CachedAddressGeocoder(
        tmp_path / "market.sqlite3",
        "ImobHunter-BR/0.1 (support@example.com)",
        client=_client([]),
    )
    with pytest.raises(GeocodingError, match="Nenhuma localização"):
        geocoder.geocode("Rua inexistente, Cidade Teste, SP")


def test_geocoder_rejects_missing_user_agent_and_too_fast_interval(tmp_path: Path):
    with pytest.raises(ValueError, match="User-Agent"):
        CachedAddressGeocoder(tmp_path / "db.sqlite3", "")
    with pytest.raises(ValueError, match="pelo menos 1 segundo"):
        CachedAddressGeocoder(
            tmp_path / "db.sqlite3",
            "ImobHunter-BR/0.1 (support@example.com)",
            minimum_interval=0.2,
        )


def test_geocoder_rejects_bad_coordinates(tmp_path: Path):
    geocoder = CachedAddressGeocoder(
        tmp_path / "market.sqlite3",
        "ImobHunter-BR/0.1 (support@example.com)",
        client=_client([{"lat": "999", "lon": "0"}]),
    )
    with pytest.raises(GeocodingError, match="fora dos limites"):
        geocoder.geocode("Rua Teste, 123, São Paulo, SP")
