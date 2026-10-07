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


class IPHANAdapter(SourceAdapter):
    """Reads official IPHAN heritage datasets for local property enrichment.

    IPHAN publishes heritage and archaeological geospatial data, including
    datasets exposed through its official geoserver. This adapter consumes an
    official local export/cache so heavy geospatial processing stays local.
    """

    source_id = "iphan"
    name = "IPHAN"
    category = "heritage"

    def __init__(self, data_path: str | Path | None = None) -> None:
        configured = data_path or os.getenv("IMOBHUNTER_IPHAN_PATH")
        self.data_path = Path(configured) if configured else None

    def status(self) -> SourceStatus:
        if not self.data_path:
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                "IPHAN uses official heritage geoservices or local official exports/cache.",
            )
        if not self.data_path.exists():
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                f"IPHAN data file not found: {self.data_path}",
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
                str(row.get("municipio") or row.get("city") or row.get("municipality") or "")
            )
            row_state = self._normalize_text(str(row.get("uf") or row.get("state") or ""))

            if city and row_city and row_city != city:
                continue
            if state and row_state and row_state != state:
                continue

            row_address = self._normalize_text(
                str(row.get("endereco") or row.get("address") or row.get("logradouro") or "")
            )
            if query_address and row_address and query_address not in row_address:
                continue

            records.append(self._to_record(row))
        return records

    def _load(self) -> list[dict[str, Any]]:
        if not self.data_path:
            return []
        if not self.data_path.exists():
            raise RuntimeError(f"IPHAN data file not found: {self.data_path}")

        suffix = self.data_path.suffix.lower()
        if suffix == ".csv":
            with self.data_path.open("r", encoding="utf-8-sig", newline="") as handle:
                return list(csv.DictReader(handle))

        payload = json.loads(self.data_path.read_text(encoding="utf-8"))
        if suffix in {".geojson", ".json"}:
            if isinstance(payload, dict) and "features" in payload:
                features = payload["features"]
                if not isinstance(features, list):
                    raise ValueError("IPHAN GeoJSON features must be a list")
                return [self._flatten_feature(feature) for feature in features]
            rows = payload.get("data", payload.get("items", payload)) if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                raise ValueError("IPHAN JSON must contain a list or GeoJSON features")
            return [self._flatten_feature(row) if isinstance(row, dict) and "properties" in row else row for row in rows]

        raise ValueError("IPHAN data must be CSV, JSON, or GeoJSON")

    @staticmethod
    def _flatten_feature(feature: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(feature, dict):
            raise TypeError("IPHAN GeoJSON feature must be an object")
        properties = feature.get("properties") or {}
        if not isinstance(properties, dict):
            raise TypeError("IPHAN feature properties must be an object")
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
        heritage_id = str(
            row.get("id")
            or row.get("id_bem")
            or row.get("codigo")
            or row.get("codigo_bem")
            or row.get("id_sitio")
            or ""
        ).strip() or None

        name = row.get("nome") or row.get("nome_bem") or row.get("nome_sitio") or row.get("name")
        protection = (
            row.get("tombamento")
            or row.get("tipo_protecao")
            or row.get("protecao")
            or row.get("protection_type")
        )
        heritage_type = row.get("tipo") or row.get("tipo_bem") or row.get("category")
        process = row.get("processo") or row.get("processo_tombamento") or row.get("process")

        latitude = float(row["latitude"]) if row.get("latitude") not in (None, "") else None
        longitude = float(row["longitude"]) if row.get("longitude") not in (None, "") else None
        geometry = row.get("geometry")
        if latitude is None and longitude is None and isinstance(geometry, dict) and geometry.get("type") == "Point":
            coordinates = geometry.get("coordinates")
            if isinstance(coordinates, list) and len(coordinates) >= 2:
                longitude = float(coordinates[0])
                latitude = float(coordinates[1])

        attributes = {
            key: row.get(key)
            for key in (
                "tombamento",
                "tipo_protecao",
                "protecao",
                "tipo",
                "tipo_bem",
                "livro_tombo",
                "processo",
                "processo_tombamento",
                "situacao",
                "ano",
                "data",
                "decreto",
                "municipio",
                "uf",
                "endereco",
                "address",
                "geometry",
            )
            if row.get(key) not in (None, "")
        }
        if name:
            attributes["heritage_name"] = name
        if heritage_id:
            attributes["iphan_id"] = heritage_id
        if protection:
            attributes["protection_type"] = protection
        if heritage_type:
            attributes["heritage_type"] = heritage_type
        if process:
            attributes["heritage_process"] = process

        return PropertyRecord(
            property_id=heritage_id,
            address=row.get("endereco") or row.get("address") or row.get("logradouro"),
            city=row.get("municipio") or row.get("city") or row.get("municipality"),
            state=row.get("uf") or row.get("state"),
            latitude=latitude,
            longitude=longitude,
            attributes=attributes,
            provenance=(Provenance(source_id="iphan", confidence=0.95),),
        )
