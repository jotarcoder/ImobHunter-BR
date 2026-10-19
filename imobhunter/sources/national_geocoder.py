from __future__ import annotations

import json
import os
from pathlib import Path

from imobhunter.application.address_geocoding import CachedAddressGeocoder, GeocodingError
from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus

from .base import SourceAdapter


class NationalAddressGeocoderAdapter(SourceAdapter):
    """National address fallback; it returns a geocoded point, never a parcel claim."""

    source_id = "national_address_geocoder"
    name = "Geocodificação nacional (OpenStreetMap)"
    category = "geospatial"

    def __init__(self, geocoder=None) -> None:
        cache_path = Path(
            os.getenv("IMOBHUNTER_GEOCODING_CACHE")
            or Path.home() / ".imobhunter" / "geocoding.sqlite3"
        )
        self.geocoder = geocoder or CachedAddressGeocoder(
            cache_path,
            os.getenv(
                "IMOBHUNTER_NOMINATIM_USER_AGENT",
                "ImobHunter-BR/0.1 (desktop address search)",
            ),
        )

    def status(self) -> SourceStatus:
        return SourceStatus(
            self.source_id,
            self.name,
            "available",
            "Geocodifica endereços no Brasil. Retorna apenas localização aproximada; "
            "não fornece lote oficial, SQL/IPTU, área cadastral nem proprietário.",
        )

    @staticmethod
    def _normalize(value: str | None) -> str:
        return " ".join((value or "").strip().casefold().split())

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        if not request.address or not request.city or not request.state:
            return []
        city = self._normalize(request.city)
        state = self._normalize(request.state)
        # GeoSampa is the authoritative configured parcel source for São Paulo
        # municipality; don't add a duplicate geocoded point for the same query.
        if city in {"são paulo", "sao paulo", "são paulo capital"} and state in {"sp", "são paulo", "sao paulo"}:
            return []
        query = ", ".join(
            part for part in (
                " ".join(part for part in (request.address, request.number) if part),
                request.city,
                request.state,
                "Brasil",
            ) if part
        )
        try:
            result = self.geocoder.geocode(query)
        except GeocodingError:
            return []
        latitude = float(result["latitude"])
        longitude = float(result["longitude"])
        point = {
            "type": "Point",
            "coordinates": [longitude, latitude],
        }
        label = str(result.get("display_name") or query)
        return [
            PropertyRecord(
                address=str(request.address),
                city=request.city,
                state=request.state,
                latitude=latitude,
                longitude=longitude,
                attributes={
                    "record_kind": "geocoded_address_only",
                    "geocoded_label": label,
                    "geometry_geojson": json.dumps(point, ensure_ascii=False),
                    "parcel_status": "not_provided_by_geocoder",
                    "sql_status": "not_provided_by_geocoder",
                    "iptu_status": "not_provided_by_geocoder",
                    "area_status": "not_provided_by_geocoder",
                    "owner_status": "not_provided_by_geocoder",
                    "map_attribution": str(result.get("attribution") or "© OpenStreetMap contributors"),
                    "geocoding_provider": str(result.get("provider") or "OpenStreetMap Nominatim"),
                    "geocoding_cached": bool(result.get("cached")),
                },
                provenance=(Provenance(
                    source_id=self.source_id,
                    confidence=0.55,
                    reference=str(result.get("provider") or "OpenStreetMap Nominatim"),
                ),),
            )
        ]
