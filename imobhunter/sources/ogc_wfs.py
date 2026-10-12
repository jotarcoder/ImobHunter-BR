from __future__ import annotations

import re
from typing import Any

import httpx

from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus
from .base import SourceAdapter


def _identifier(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:-]*", value):
        raise ValueError(f"Invalid WFS field/layer identifier: {value!r}")
    return value


def _value(properties: dict[str, Any], field: str) -> Any:
    if not field:
        return None
    direct = properties.get(field)
    if direct not in (None, ""):
        return direct
    folded = {str(key).casefold(): value for key, value in properties.items()}
    return folded.get(field.casefold())


class ConfigurableWFSAdapter(SourceAdapter):
    """Generic, user-configured OGC WFS adapter for authorized municipal layers.

    Layer and field names vary between municipalities; no undocumented schema is
    assumed. The adapter only queries the endpoint/layer explicitly configured
    by the user and records the original feature properties as provenance.
    """

    source_id = "municipal_wfs"
    name = "Geosserviço municipal (WFS)"
    category = "municipal"

    def __init__(
        self,
        endpoint: str = "",
        layer: str = "",
        address_field: str = "logradouro",
        number_field: str = "numero",
        block_field: str = "quadra",
        lot_field: str = "lote",
        area_field: str = "area_m2",
        id_field: str = "id",
        timeout: float = 20.0,
        client: Any | None = None,
    ) -> None:
        self.endpoint = endpoint.strip()
        self.layer = layer.strip()
        self.address_field = address_field.strip()
        self.number_field = number_field.strip()
        self.block_field = block_field.strip()
        self.lot_field = lot_field.strip()
        self.area_field = area_field.strip()
        self.id_field = id_field.strip()
        self.timeout = timeout
        self._client = client

    def status(self) -> SourceStatus:
        if not self.endpoint or not self.layer:
            return SourceStatus(
                self.source_id, self.name, "not_configured",
                "Configure o endpoint WFS autorizado e o nome exato da camada.",
            )
        return SourceStatus(
            self.source_id, self.name, "configured",
            "Endpoint/camada configurados; a disponibilidade será confirmada na consulta.",
        )

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        if not self.endpoint or not self.layer:
            return []
        layer = _identifier(self.layer)
        filters: list[str] = []
        block, lot = (request.block or "").strip(), (request.lot or "").strip()
        if block and lot:
            if self.block_field:
                filters.append(f"{_identifier(self.block_field)}='{self._escape(block)}'")
            if self.lot_field:
                filters.append(f"{_identifier(self.lot_field)}='{self._escape(lot)}'")
        elif request.address:
            if not self.address_field:
                return []
            filters.append(
                f"{_identifier(self.address_field)} ILIKE '%{self._escape(request.address)}%'"
            )
            if request.number and self.number_field:
                filters.append(
                    f"{_identifier(self.number_field)}='{self._escape(request.number)}'"
                )
        else:
            return []

        params: dict[str, str | int] = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": layer, "outputFormat": "application/json", "count": 100,
        }
        if filters:
            params["CQL_FILTER"] = " AND ".join(filters)

        client = self._client or httpx.Client(timeout=self.timeout)
        close_client = self._client is None
        try:
            response = client.get(self.endpoint, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Municipal WFS request failed: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("Municipal WFS returned invalid JSON") from exc
        finally:
            if close_client:
                client.close()

        features = payload.get("features", []) if isinstance(payload, dict) else []
        records: list[PropertyRecord] = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties") or {}
            geometry = feature.get("geometry") or {}
            lat, lon = self._point(geometry)
            raw_area = _value(properties, self.area_field)
            try:
                area = float(str(raw_area).replace(",", ".")) if raw_area not in (None, "") else None
            except (TypeError, ValueError):
                area = None
            prop_id = _value(properties, self.id_field) if self.id_field else feature.get("id")
            records.append(PropertyRecord(
                property_id=str(prop_id) if prop_id not in (None, "") else None,
                address=str(_value(properties, self.address_field)) if _value(properties, self.address_field) not in (None, "") else request.address,
                city=request.city,
                state=request.state,
                block=str(_value(properties, self.block_field)) if _value(properties, self.block_field) not in (None, "") else request.block,
                lot=str(_value(properties, self.lot_field)) if _value(properties, self.lot_field) not in (None, "") else request.lot,
                area_m2=area,
                latitude=lat,
                longitude=lon,
                attributes={"source": self.name, "wfs_layer": layer, "properties": properties},
                provenance=(Provenance(self.source_id, confidence=0.85, reference=str(prop_id) if prop_id else None),),
            ))
        return records

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("'", "''")

    @staticmethod
    def _point(geometry: dict[str, Any]) -> tuple[float | None, float | None]:
        kind, coords = geometry.get("type"), geometry.get("coordinates")
        if kind == "Point" and isinstance(coords, list) and len(coords) >= 2:
            return float(coords[1]), float(coords[0])
        points: list[tuple[float, float]] = []
        def visit(value: Any) -> None:
            if isinstance(value, list) and len(value) >= 2 and all(isinstance(x, (int, float)) for x in value[:2]):
                points.append((float(value[1]), float(value[0])))
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(coords)
        if not points:
            return None, None
        return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)
