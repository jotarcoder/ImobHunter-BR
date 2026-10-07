from __future__ import annotations

import csv
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus

from .base import SourceAdapter


class OSMAdapter(SourceAdapter):
    """Reads OpenStreetMap extracts/cache files for local geospatial context.

    The adapter deliberately does not call the public Nominatim/Overpass
    services automatically. Heavy processing stays local, while online OSM
    services can be added later behind explicit, rate-limited configuration.
    """

    source_id = "osm"
    name = "OpenStreetMap"
    category = "geospatial"

    def __init__(self, data_path: str | Path | None = None) -> None:
        configured = data_path or os.getenv("IMOBHUNTER_OSM_PATH")
        self.data_path = Path(configured) if configured else None

    def status(self) -> SourceStatus:
        if not self.data_path:
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                "Configure an official/open OSM extract or local cache for local processing.",
            )
        if not self.data_path.exists():
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                f"OpenStreetMap data file not found: {self.data_path}",
            )
        return SourceStatus(self.source_id, self.name, "configured")

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        rows = self._load()
        city = self._normalize_text(request.city or "")
        state = self._normalize_text(request.state or "")
        query_address = self._normalize_text(
            " ".join(part for part in (request.address, request.number) if part)
        )

        records: list[PropertyRecord] = []
        for row in rows:
            row_city = self._normalize_text(
                str(row.get("municipio") or row.get("city") or row.get("addr:city") or "")
            )
            row_state = self._normalize_text(
                str(row.get("uf") or row.get("state") or row.get("addr:state") or "")
            )
            if city and row_city and row_city != city:
                continue
            if state and row_state and row_state != state:
                continue

            row_address = self._normalize_text(
                str(
                    row.get("endereco")
                    or row.get("address")
                    or row.get("logradouro")
                    or row.get("addr:street")
                    or ""
                )
            )
            row_number = str(row.get("numero") or row.get("addr:housenumber") or "").strip()
            if row_number and row_address:
                row_address = self._normalize_text(f"{row_address} {row_number}")
            if query_address and row_address:
                if query_address not in row_address:
                    continue
            elif query_address and not row_address:
                continue

            records.append(self._to_record(row))
        return records

    def _load(self) -> list[dict[str, Any]]:
        if not self.data_path:
            return []
        if not self.data_path.exists():
            raise RuntimeError(f"OpenStreetMap data file not found: {self.data_path}")

        suffix = self.data_path.suffix.lower()
        if suffix == ".csv":
            with self.data_path.open("r", encoding="utf-8-sig", newline="") as handle:
                return list(csv.DictReader(handle))

        payload = json.loads(self.data_path.read_text(encoding="utf-8"))
        if suffix == ".jsonl":
            return [
                json.loads(line)
                for line in self.data_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        if suffix in {".json", ".geojson"}:
            if isinstance(payload, dict) and "features" in payload:
                features = payload["features"]
                if not isinstance(features, list):
                    raise ValueError("OSM GeoJSON features must be a list")
                return [self._flatten_feature(feature) for feature in features]
            rows = payload.get("data", payload.get("items", payload)) if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                raise ValueError("OSM JSON must contain a list or GeoJSON features")
            return [
                self._flatten_feature(row)
                if isinstance(row, dict) and "properties" in row
                else row
                for row in rows
            ]

        raise ValueError("OpenStreetMap data must be CSV, JSON, GeoJSON, or JSONL")

    @staticmethod
    def _flatten_feature(feature: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(feature, dict):
            raise TypeError("OSM GeoJSON feature must be an object")
        properties = feature.get("properties") or {}
        if not isinstance(properties, dict):
            raise TypeError("OSM feature properties must be an object")
        row = dict(properties)
        geometry = feature.get("geometry")
        if geometry is not None:
            row["geometry"] = geometry
        return row

    @staticmethod
    def _normalize_text(value: str) -> str:
        text = unicodedata.normalize("NFKD", value)
        text = "".join(char for char in text if not unicodedata.combining(char))
        text = text.upper()
        text = re.sub(r"[^A-Z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _to_record(row: dict[str, Any]) -> PropertyRecord:
        osm_id = str(
            row.get("osm_id")
            or row.get("id")
            or row.get("@id")
            or ""
        ).strip() or None
        name = row.get("name") or row.get("nome")
        feature_type = (
            row.get("feature_type")
            or row.get("type")
            or row.get("amenity")
            or row.get("shop")
            or row.get("building")
            or row.get("landuse")
            or row.get("tourism")
        )
        category = row.get("category") or row.get("categoria") or feature_type
        latitude = OSMAdapter._number(row.get("latitude") or row.get("lat"))
        longitude = OSMAdapter._number(row.get("longitude") or row.get("lon"))
        geometry = row.get("geometry")

        if (
            latitude is None
            and longitude is None
            and isinstance(geometry, dict)
            and geometry.get("type") == "Point"
        ):
            coordinates = geometry.get("coordinates")
            if isinstance(coordinates, list) and len(coordinates) >= 2:
                longitude = OSMAdapter._number(coordinates[0])
                latitude = OSMAdapter._number(coordinates[1])

        attributes = {
            key: row.get(key)
            for key in (
                "name",
                "feature_type",
                "type",
                "amenity",
                "shop",
                "building",
                "landuse",
                "tourism",
                "category",
                "categoria",
                "addr:housenumber",
                "addr:postcode",
                "addr:street",
                "addr:city",
                "addr:state",
                "addr:postcode",
                "geometry",
            )
            if row.get(key) not in (None, "")
        }
        tags = row.get("tags")
        if tags not in (None, ""):
            attributes["osm_tags"] = tags
        if name:
            attributes["osm_name"] = name
        if feature_type:
            attributes["osm_feature_type"] = feature_type
        if category:
            attributes["osm_category"] = category

        address = (
            row.get("endereco")
            or row.get("address")
            or row.get("logradouro")
            or row.get("addr:street")
        )
        house_number = row.get("numero") or row.get("addr:housenumber")
        if house_number and address:
            address = f"{address}, {house_number}"

        return PropertyRecord(
            property_id=f"osm:{osm_id}" if osm_id else None,
            address=address,
            city=row.get("municipio") or row.get("city") or row.get("addr:city"),
            state=row.get("uf") or row.get("state") or row.get("addr:state"),
            latitude=latitude,
            longitude=longitude,
            attributes=attributes,
            provenance=(
                Provenance(
                    source_id="osm",
                    confidence=0.85,
                    reference="https://www.openstreetmap.org/copyright",
                ),
            ),
        )

    @staticmethod
    def _number(value: Any) -> float | None:
        if value in (None, ""):
            return None
        return float(value)
