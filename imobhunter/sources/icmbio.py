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


class ICMBioAdapter(SourceAdapter):
    """Reads official/open ICMBio geospatial exports for environmental enrichment.

    The official ICMBio geoservices are exposed through INDE WFS/WMS. This
    adapter keeps heavy geospatial data local and consumes an authorized or
    official local export/cache in CSV, JSON, or GeoJSON form.
    """

    source_id = "icmbio"
    name = "ICMBio"
    category = "environmental"

    def __init__(self, data_path: str | Path | None = None) -> None:
        configured = data_path or os.getenv("IMOBHUNTER_ICMBIO_PATH")
        self.data_path = Path(configured) if configured else None

    def status(self) -> SourceStatus:
        if not self.data_path:
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                "ICMBio uses official INDE geoservices or a local official export/cache.",
            )
        if not self.data_path.exists():
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                f"ICMBio data file not found: {self.data_path}",
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
            row_state = self._normalize_text(
                str(row.get("uf") or row.get("state") or "")
            )
            row_address = self._normalize_text(
                str(
                    row.get("endereco")
                    or row.get("address")
                    or row.get("localizacao")
                    or row.get("location")
                    or ""
                )
            )

            if city and row_city and row_city != city:
                continue
            if state and row_state and row_state != state:
                continue

            # Environmental layers are primarily spatial. When an address is
            # present in the export, use it as an additional filter; otherwise
            # retain the record for municipality-level enrichment.
            if query_address and row_address and query_address not in row_address:
                continue

            records.append(self._to_record(row))
        return records

    def _load(self) -> list[dict[str, Any]]:
        if not self.data_path:
            return []
        if not self.data_path.exists():
            raise RuntimeError(f"ICMBio data file not found: {self.data_path}")

        suffix = self.data_path.suffix.lower()
        if suffix == ".csv":
            with self.data_path.open("r", encoding="utf-8-sig", newline="") as handle:
                return list(csv.DictReader(handle))

        if suffix == ".json":
            payload = json.loads(self.data_path.read_text(encoding="utf-8"))
            rows = payload.get("features", payload) if isinstance(payload, dict) else payload
            if isinstance(rows, dict):
                rows = rows.get("data", rows.get("items"))
            if not isinstance(rows, list):
                raise ValueError("ICMBio JSON must contain a list or GeoJSON features")
            return [self._flatten_feature(row) for row in rows]

        if suffix in {".geojson", ".jsonl"}:
            if suffix == ".jsonl":
                return [
                    json.loads(line)
                    for line in self.data_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            payload = json.loads(self.data_path.read_text(encoding="utf-8"))
            features = payload.get("features", []) if isinstance(payload, dict) else []
            if not isinstance(features, list):
                raise ValueError("ICMBio GeoJSON features must be a list")
            return [self._flatten_feature(feature) for feature in features]

        raise ValueError("ICMBio data must be CSV, JSON, GeoJSON, or JSONL")

    @staticmethod
    def _flatten_feature(feature: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(feature, dict):
            raise TypeError("ICMBio GeoJSON feature must be an object")
        properties = feature.get("properties") or {}
        if not isinstance(properties, dict):
            raise TypeError("ICMBio feature properties must be an object")
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
        unit_id = str(
            row.get("id")
            or row.get("id_uc")
            or row.get("codigo")
            or row.get("codigo_uc")
            or row.get("cod_uc")
            or ""
        ).strip() or None
        name = (
            row.get("nome")
            or row.get("nome_uc")
            or row.get("nomeUnidade")
            or row.get("unidade")
            or row.get("name")
        )
        category = (
            row.get("categoria")
            or row.get("categoria_uc")
            or row.get("categoriaUC")
            or row.get("category")
        )
        biome = row.get("bioma") or row.get("biome")
        management = (
            row.get("gestao")
            or row.get("gestao_uc")
            or row.get("orgao_gestor")
            or row.get("manager")
        )
        area = row.get("area_m2")
        if area in (None, ""):
            hectares = row.get("area_ha") or row.get("area_hectares")
            area = float(hectares) * 10_000 if hectares not in (None, "") else None
        else:
            area = float(area)

        attributes = {
            key: row.get(key)
            for key in (
                "categoria",
                "categoria_uc",
                "grupo",
                "bioma",
                "gestao",
                "orgao_gestor",
                "municipio",
                "uf",
                "ano_criacao",
                "data_criacao",
                "decreto",
                "plano_manejo",
                "situacao",
                "tipo",
                "subtipo",
                "area_ha",
                "area_hectares",
                "geometry",
            )
            if row.get(key) not in (None, "")
        }
        if name:
            attributes["environmental_name"] = name
        if unit_id:
            attributes["icmbio_id"] = unit_id
        if category:
            attributes["environmental_category"] = category
        if biome:
            attributes["biome"] = biome
        if management:
            attributes["management"] = management

        latitude = float(row["latitude"]) if row.get("latitude") not in (None, "") else None
        longitude = float(row["longitude"]) if row.get("longitude") not in (None, "") else None
        geometry = row.get("geometry")
        if latitude is None and longitude is None and isinstance(geometry, dict) and geometry.get("type") == "Point":
            coordinates = geometry.get("coordinates")
            if isinstance(coordinates, list) and len(coordinates) >= 2:
                longitude = float(coordinates[0])
                latitude = float(coordinates[1])

        return PropertyRecord(
            property_id=unit_id,
            address=row.get("endereco") or row.get("address") or row.get("localizacao"),
            city=row.get("municipio") or row.get("city") or row.get("municipality"),
            state=row.get("uf") or row.get("state"),
            area_m2=area,
            latitude=latitude,
            longitude=longitude,
            attributes=attributes,
            provenance=(Provenance(source_id="icmbio", confidence=0.95),),
        )
