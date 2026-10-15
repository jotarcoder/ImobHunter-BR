from __future__ import annotations

from typing import Any

import httpx
import json

from imobhunter.application.address import normalize_request
from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus

from .base import SourceAdapter

DEFAULT_WFS_URL = "https://geoserver.slui.dev/geoserver/slui/ows"
DEFAULT_LAYER = "slui:view_lote_cidadao"


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
            message=(
                "Camada cadastral municipal de São Paulo: lote, quadra, SQL/IPTU, "
                "área e geometria quando fornecidos. Esta camada não confirma, por si só, "
                "nome/CPF do proprietário nem débitos atuais."
            ),
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
        block = (request.block or "").strip()
        lot = (request.lot or "").strip()
        if block and lot:
            filters = [
                f"cd_quadra_fiscal='{_escape_cql(block)}'",
                f"cd_lote='{_escape_cql(lot)}'",
            ]
        else:
            if not normalized.street_name:
                return []
            # Wildcards between tokens tolerate source abbreviations and spacing.
            street_term = "%".join(
                token for token in normalized.street_name.split() if token
            )
            filters = [
                f"nm_logradouro_completo ILIKE '%{_escape_cql(street_term)}%'",
            ]
            # Address-only searches should return candidate parcels instead of
            # silently returning no results. Keep the exact door-number filter
            # when the user supplied one.
            if normalized.number:
                filters.append(
                    f"cd_numero_porta='{_escape_cql(normalized.number)}'"
                )
        # Primeiro tenta o endereço exato. Se o cadastro municipal tiver
        # número predial ausente/diferente, repete por logradouro para não
        # transformar uma divergência cadastral em uma busca vazia.
        query_filters = [filters]
        if normalized.number and not (block and lot):
            street_term = "%".join(
                token for token in (normalized.street_name or "").split() if token
            )
            query_filters.append([
                f"nm_logradouro_completo ILIKE '%{_escape_cql(street_term)}%'"
            ])

        client = self._client or httpx.Client(timeout=self.timeout)
        close_client = self._client is None
        try:
            records: list[PropertyRecord] = []
            for active_filters in query_filters:
                params = {
                    "service": "WFS",
                    "version": "1.0.0",
                    "request": "GetFeature",
                    "typeName": self.layer,
                    "outputFormat": "json",
                    "srsName": "EPSG:4326",
                    "CQL_FILTER": " AND ".join(active_filters),
                    "maxFeatures": 50,
                }
                try:
                    response = client.get(self.endpoint, params=params, timeout=self.timeout)
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    raise RuntimeError(f"GeoSampa request failed: {exc}") from exc
                content_type = response.headers.get("content-type", "").lower()
                try:
                    payload = response.json()
                except ValueError as exc:
                    body = " ".join(response.text.split())[:240]
                    if "xml" in content_type or body.startswith("<"):
                        detail = "WFS devolveu XML em vez de GeoJSON"
                    elif "html" in content_type or "<html" in body.lower():
                        detail = "WFS devolveu HTML em vez de GeoJSON"
                    else:
                        detail = "WFS devolveu conteúdo que não é JSON válido"
                    raise RuntimeError(
                        f"GeoSampa: {detail}; HTTP {response.status_code}; "
                        f"Content-Type={content_type or 'ausente'}; resposta={body or '(vazia)'}"
                    ) from exc
                if not isinstance(payload, dict):
                    raise TypeError("GeoSampa: resposta JSON válida, mas não é um objeto GeoJSON")
                if payload.get("type") == "ExceptionReport" or "ServiceException" in payload:
                    raise RuntimeError("GeoSampa WFS reportou uma exceção: " + " ".join(str(payload)[:300].split()))
                records = self._parse_features(payload)
                if records:
                    break
        finally:
            if close_client:
                client.close()

        return records

    def _parse_features(self, payload: dict[str, Any]) -> list[PropertyRecord]:
        records: list[PropertyRecord] = []
        for feature in payload.get("features", []):
            properties = feature.get("properties") or {}
            geometry = feature.get("geometry") or {}
            latitude, longitude = _representative_point(geometry)
            # Preserve the real GeoJSON polygon so the desktop map can render it.
            safe_geometry = geometry if geometry.get("type") in {"Point", "Polygon", "MultiPolygon"} else {}
            geometry_json = json.dumps(safe_geometry, separators=(",", ":"), allow_nan=False) if safe_geometry else None

            setor = _text(properties, "cd_setor_fiscal", "setor")
            quadra = _text(properties, "cd_quadra_fiscal", "quadra")
            lote = _text(properties, "cd_lote", "lote")
            digito = _text(properties, "cd_digito_sql", "digito_sql")
            sql = _text(properties, "nr_contribuinte")
            if not sql and setor and quadra and lote and digito:
                sql = f"{setor}.{quadra}.{lote}-{digito}"
            # The public cadastral layer's SQL/IPTU number identifies the fiscal
            # registration; it must not be presented as proof of legal ownership.
            property_id = sql or _text(
                properties,
                "nr_contribuinte",
                "cd_contribuinte",
                "codigo_contribuinte",
                "cd_identificador",
                "cd_identificador_original_lote",
            )
            cib = _text(properties, "cd_cib")
            taxpayer_name = _text(
                properties, "nm_contribuinte", "nome_contribuinte", "contribuinte"
            )
            reference_year = _text(
                properties, "ano_referencia", "ano_base", "exercicio", "year"
            )

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
                        "qt_area_terreno_calc",
                        "area_terreno",
                    ),
                    latitude=latitude,
                    longitude=longitude,
                    attributes={
                        "source": self.source_id,
                        "geometry_geojson": geometry_json,
                        "source_scope": "municipal_fiscal_cadastre",
                        "sector": setor,
                        "sql": sql,
                        # Registration SQL and taxpayer name are separate fields.
                        "iptu_contributor": taxpayer_name,
                        "iptu_registration_number": sql,
                        "taxpayer_name": taxpayer_name,
                        "taxpayer_name_status": (
                            "not_provided_by_this_layer" if not taxpayer_name
                            else "provided_by_source"
                        ),
                        "iptu_reference_year": reference_year,
                        "iptu_data_scope": (
                            "historical" if reference_year and reference_year.isdigit()
                            and int(reference_year) <= 2016 else "unspecified"
                        ),
                        "iptu_current_debt_status": "not_provided_by_this_layer",
                        "owner_document_status": (
                            "not_provided_by_this_layer" if not _text(
                                properties, "nr_cpf_cnpj", "cpf_cnpj", "documento_contribuinte"
                            ) else "provided_by_source"
                        ),
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
                        "block_type": _text(properties, "tx_tipo_quadra", "cd_tipo_quadra"),
                        "property_use_type": _text(properties, "tipo_uso_imovel"),
                        "land_type": _text(properties, "tipo_terreno_imovel"),
                        "frontage_m": _float(properties, "qt_testada_calculo"),
                        "owner_name_from_source": _text(properties, "nm_proprietario"),
                        "commitment_holder_from_source": _text(properties, "nm_compromissario"),
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
