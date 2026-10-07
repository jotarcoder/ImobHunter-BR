from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GeospatialService:
    service_id: str
    title: str
    provider: str | None = None
    service_type: str | None = None
    url: str | None = None
    layer: str | None = None
    keywords: tuple[str, ...] = ()
    state: str | None = None
    city: str | None = None
    updated_at: str | None = None


class INDECatalog:
    """Reads an authorized INDE catalog export for geoservice discovery.

    INDE is a discovery/catalog layer for OGC geoservices (WMS/WFS/WCS),
    not a property-record source. The catalog is intentionally kept outside
    PropertyRecord reconciliation.
    """

    def __init__(self, data_path: str | Path | None = None) -> None:
        self.data_path = Path(data_path) if data_path else None

    def status(self) -> str:
        if not self.data_path:
            return "not_configured"
        return "configured" if self.data_path.exists() else "missing"

    def load(self) -> list[GeospatialService]:
        if not self.data_path:
            return []
        if not self.data_path.exists():
            raise FileNotFoundError(f"INDE catalog not found: {self.data_path}")

        suffix = self.data_path.suffix.lower()
        if suffix == ".csv":
            return self._load_csv()
        if suffix == ".json":
            return self._load_json()
        raise ValueError("INDE catalog must be CSV or JSON")

    def search(
        self,
        *,
        text: str | None = None,
        state: str | None = None,
        city: str | None = None,
        service_type: str | None = None,
    ) -> list[GeospatialService]:
        services = self.load()
        needle = text.casefold() if text else None
        wanted_state = state.casefold() if state else None
        wanted_city = city.casefold() if city else None
        wanted_type = service_type.casefold() if service_type else None

        result: list[GeospatialService] = []
        for service in services:
            haystack = " ".join(
                (service.title, service.provider or "", service.layer or "", *service.keywords)
            ).casefold()
            if needle and needle not in haystack:
                continue
            if wanted_state and (service.state or "").casefold() != wanted_state:
                continue
            if wanted_city and (service.city or "").casefold() != wanted_city:
                continue
            if wanted_type and (service.service_type or "").casefold() != wanted_type:
                continue
            result.append(service)
        return result

    def _load_csv(self) -> list[GeospatialService]:
        with self.data_path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [self._from_mapping(row) for row in csv.DictReader(handle)]

    def _load_json(self) -> list[GeospatialService]:
        payload = json.loads(self.data_path.read_text(encoding="utf-8"))
        rows: Any = payload.get("services", payload) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("INDE JSON catalog must contain a list of services")
        return [self._from_mapping(row) for row in rows]

    @staticmethod
    def _from_mapping(row: dict[str, Any]) -> GeospatialService:
        keywords = row.get("keywords", ())
        if isinstance(keywords, str):
            keywords = tuple(item.strip() for item in keywords.split(",") if item.strip())
        else:
            keywords = tuple(str(item) for item in keywords or ())

        return GeospatialService(
            service_id=str(row.get("service_id") or row.get("id") or ""),
            title=str(row.get("title") or row.get("name") or ""),
            provider=row.get("provider"),
            service_type=row.get("service_type") or row.get("type"),
            url=row.get("url"),
            layer=row.get("layer") or row.get("type_name"),
            keywords=keywords,
            state=row.get("state") or row.get("uf"),
            city=row.get("city") or row.get("municipality"),
            updated_at=row.get("updated_at"),
        )
