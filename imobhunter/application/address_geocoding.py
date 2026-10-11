from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
MIN_REQUEST_INTERVAL_SECONDS = 1.1


class GeocodingError(ValueError):
    """A safe, user-displayable geocoding error."""


class CachedAddressGeocoder:
    """Single-address geocoder with a local SQLite cache and explicit rate limiting.

    This intentionally does not implement bulk geocoding. The public Nominatim service
    requires an identifying User-Agent, attribution, and a maximum of one request per
    second. For large-scale workloads, configure a provider that explicitly permits it.
    """

    def __init__(
        self,
        database_path: str | Path,
        user_agent: str,
        *,
        client: httpx.Client | None = None,
        minimum_interval: float = MIN_REQUEST_INTERVAL_SECONDS,
    ) -> None:
        if not user_agent.strip() or "your-app" in user_agent.lower():
            raise ValueError("Informe um User-Agent identificável para o ImobHunter.")
        if minimum_interval < 1.0:
            raise ValueError("O intervalo mínimo deve ser de pelo menos 1 segundo.")
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent.strip()
        self.minimum_interval = minimum_interval
        self._client = client
        self._last_request_at = 0.0
        with sqlite3.connect(self.database_path) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS geocoding_cache (
                    query_hash TEXT PRIMARY KEY,
                    query_text TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    display_name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    attribution TEXT NOT NULL,
                    cached_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

    @staticmethod
    def _normalize(address: str) -> str:
        return " ".join(address.split())

    def _cached(self, query_hash: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.database_path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT * FROM geocoding_cache WHERE query_hash=?", (query_hash,)
            ).fetchone()
        return dict(row) if row else None

    def geocode(self, address: str) -> dict[str, Any]:
        query = self._normalize(address)
        if len(query) < 5:
            raise GeocodingError("Informe um endereço mais completo para localizar.")
        query_hash = hashlib.sha256(query.casefold().encode("utf-8")).hexdigest()
        cached = self._cached(query_hash)
        if cached:
            cached["cached"] = True
            return cached

        owned_client = self._client is None
        client = self._client or httpx.Client(
            timeout=httpx.Timeout(12.0),
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
            follow_redirects=True,
        )
        client.headers["User-Agent"] = self.user_agent
        client.headers["Accept"] = "application/json"
        try:
            wait = self.minimum_interval - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            response = client.get(
                NOMINATIM_URL,
                params={"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 0},
            )
            self._last_request_at = time.monotonic()
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GeocodingError(
                "Não foi possível consultar o serviço de mapas agora. Tente novamente mais tarde."
            ) from exc
        finally:
            if owned_client:
                client.close()

        if not isinstance(payload, list) or not payload:
            raise GeocodingError(
                "Nenhuma localização encontrada. Inclua rua, número, cidade e UF."
            )
        item = payload[0]
        try:
            latitude = float(item["lat"])
            longitude = float(item["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GeocodingError("O serviço retornou coordenadas inválidas.") from exc
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise GeocodingError("O serviço retornou coordenadas fora dos limites válidos.")

        result = {
            "query_text": query,
            "latitude": latitude,
            "longitude": longitude,
            "display_name": str(item.get("display_name") or query),
            "provider": "OpenStreetMap Nominatim",
            "attribution": "© OpenStreetMap contributors",
            "cached": False,
        }
        with sqlite3.connect(self.database_path) as db:
            db.execute("""
                INSERT OR REPLACE INTO geocoding_cache
                (query_hash, query_text, latitude, longitude, display_name, provider, attribution)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                query_hash, result["query_text"], latitude, longitude,
                result["display_name"], result["provider"], result["attribution"],
            ))
        return result
