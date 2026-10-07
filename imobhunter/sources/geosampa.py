from __future__ import annotations

from typing import Any

import httpx

from imobhunter.application.address import normalize_request
from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus

from .base import SourceAdapter

DEFAULT_WFS_URL = "https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/ows"
DEFAULT_LAYER = "geoportal:lote_cidadao"


def _text(properties: dict[str, Any], *names: str) -> str | None:
    lowered = {str(key).lower(): value for key, value in properties.items()}
    for name in names:
        value = properties.get(name, lowered.get(name.lower()))
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _float(properties: dict[str, Any], *names: str) -> float | None:
    value = _text(properties, *names)
    if value is None:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _escape_cql(value: str) -> str:
    return value.replace("'", "''")


def _representative_point(geometry: dict[str, Any]) -> tuple[float | None, float | None]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")

    if geometry_type == "Point" and isinstance(coordinates, list) and len(coordinates) >= 2:
        return float(coordinates[1]), float(coordinates[0])

    rings: list[list[list[float]]] = []
    if geometry_type == "Polygon" and isinstance(coordinates, list):
        rings = [ring for ring in coordinates if isinstance(ring, list)]
    elif geometry_type == "MultiPolygon" and isinstance(coordinates, list):
        rings = [
            ring
            for polygon in coordinates
            if isinstance(polygon, list)
            for ring in polygon
            if isinstance(ring, list)
        ]

    points = [
        (float(point[1]), float(point[0]))
        for ring in rings
        for point in ring
        if isinstance(point, list) and len(point) >= 2
    ]
    if not points:
        return None, None

    latitude = sum(point[0] for point in points) / len(points)
    longitude = sum(point[1] for point in points) / len(points)
    return latitude, longitude


class GeoSampaAdapter(SourceAdapter):
    source_id = "geosampa"
    name = "GeoSampa"
    category = "municipal"

    def __init__(
        self,
        endpoint: str = DEFAULT_WFS_URL,
        layer: str = DEFAULT_LAYER,
        timeout: float = 20.0,
        client: Any | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.layer = layer
        self.timeout = timeout
        self._client = client

    def status(self) -> SourceStatus:
        return SourceStatus(
            source_id=self.source_id,
            name=self.name,
            status="available",
            message="GeoSampa WFS cadastral layer configured",
        )

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        if (request.state or "").strip().upper() not in ("", "SP"):
            return []
        if request.city and " ".join(request.city.upper().split()) not in {
            "SAO PAULO",
            "SÃO PAULO",
        }:
            return []

        normalized = normalize_request(request)
        if not normalized.street_name or not normalized.number:
            return []

        filters = [
            f"nm_logradouro_completo ILIKE '%{_escape_cql(normalized.street_name)}%'",
            f"cd_numero_porta='{_escape_cql(normalized.number)}'",
        ]
        cql_filter = " AND ".join(filters)
        params = {
            "service": "WFS",
            "version": "1.0.0",
            "request": "GetFeature",
            "typeName": self.layer,
            "outputFormat": "application/json",
            "CQL_FILTER": cql_filter,
            "maxFeatures": 50,
        }

        client = self._client or httpx.Client(timeout=self.timeout)
        close_client = self._client is None
        try:
            response = client.get(self.endpoint, params=params)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return []
        finally:
            if close_client:
                client.close()

        return self._parse_features(payload)

    def _parse_features(self, payload: dict[str, Any]) -> list[PropertyRecord]:
        records: list[PropertyRecord] = []
        for feature in payload.get("features", []):
            properties = feature.get("properties") or {}
            geometry = feature.get("geometry") or {}
            latitude, longitude = _representative_point(geometry)

            setor = _text(properties, "cd_setor_fiscal", "setor")
            quadra = _text(properties, "cd_quadra_fiscal", "quadra")
            lote = _text(properties, "cd_lote", "lote")
            digito = _text(properties, "cd_digito_sql", "digito_sql")
            sql = _text(properties, "nr_contribuinte")
            if not sql and setor and quadra and lote and digito:
                sql = f"{setor}.{quadra}.{lote}-{digito}"
            property_id = _text(
                properties,
                "cd_identificador",
                "cd_identificador_original_lote",
                "nr_contribuinte",
                "cd_contribuinte",
                "codigo_contribuinte",
            )
            cib = _text(properties, "cd_cib")

            records.append(
                PropertyRecord(
                    property_id=property_id,
                    cib=cib,
                    address=_text(
                        properties,
                        "nm_logradouro_completo",
                        "nm_logradouro",
                    ),
                    city="SAO PAULO",
                    state="SP",
                    block=quadra,
                    lot=lote,
                    area_m2=_float(
                        properties,
                        "qt_area_terreno",
                        "area_terreno",
                    ),
                    latitude=latitude,
                    longitude=longitude,
                    attributes={
                        "source": self.source_id,
                        "sector": setor,
                        "sql": sql,
                        "cib": cib,
                        "built_area_m2": _float(properties, "qt_area_construida"),
                        "street_code": _text(properties, "cd_logradouro"),
                        "condominium": _text(properties, "cd_condominio"),
                        "complement": _text(properties, "tx_complemento_endereco"),
                        "door_number": _text(
                            properties,
                            "cd_numero_porta",
                            "numero_porta",
                        ),
                        "lot_type": _text(properties, "tx_tipo_lote", "tipo_lote"),
                        "lot_status": _text(
                            properties,
                            "tx_situ_lote",
                            "situacao_lote",
                        ),
                    },
                    provenance=(
                        Provenance(
                            source_id=self.source_id,
                            confidence=0.95,
                            reference=sql or property_id,
                        ),
                    ),
                )
            )
        return records
