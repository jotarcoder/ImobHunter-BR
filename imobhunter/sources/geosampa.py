from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import json

from imobhunter.application.address_geocoding import CachedAddressGeocoder, GeocodingError

from imobhunter.application.address import normalize_request
from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus

from .base import SourceAdapter

DEFAULT_WFS_URL = "https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs"
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


def _normalize_number(value: str) -> str:
    return "".join(str(value or "").upper().split())


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
        geocoder: Any | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.layer = layer
        self.timeout = timeout
        self._client = client
        self._geocoder = geocoder
        # Mocked HTTP clients in unit tests should never trigger external
        # geocoding unless a fake/real geocoder is explicitly injected.
        self._geocoding_enabled = geocoder is not None or client is None

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
            street_filter = f"nm_logradouro_completo ILIKE '%{_escape_cql(street_term)}%'"
            # GeoServer layers may expose the door number as an integer even
            # though the address form supplies text. Try the numeric CQL
            # literal as a second exact lookup before falling back to all
            # parcels on the street.
            if normalized.number.isdigit():
                query_filters.append([
                    street_filter,
                    f"cd_numero_porta={normalized.number}",
                ])
            query_filters.append([street_filter])

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
                    # Keep street-only fallback bounded. Exact number variants
                # are attempted separately before this broader candidate query.
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
                if not records:
                    continue

                if normalized.number and not (block and lot):
                    requested_number = _normalize_number(normalized.number)
                    exact_matches = [
                        record for record in records
                        if _normalize_number(
                            str(record.attributes.get("door_number") or "")
                        ) == requested_number
                    ]
                    if exact_matches:
                        for record in exact_matches:
                            record.attributes["house_number_match"] = "exact"
                        records = exact_matches
                        break

                    # If an exact-number query returned nothing, try the
                    # street-only fallback. If the fallback still has no
                    # number match, keep parcels as candidates but mark them
                    # explicitly so the UI/dossier cannot imply an exact match.
                    if len(query_filters) > 1 and active_filters is not query_filters[-1]:
                        records = []
                        continue
                    for record in records:
                        record.attributes["house_number_match"] = "candidate_only"
                    break

                break
        finally:
            if close_client:
                client.close()

        if (
            normalized.number
            and not (block and lot)
            and self._geocoding_enabled
            and (
                not records
                or all(
                    record.attributes.get("house_number_match") == "candidate_only"
                    for record in records
                )
            )
        ):
            try:
                spatial_records = self._search_by_geocoded_point(request, normalized)
                if spatial_records:
                    records = spatial_records
            except (GeocodingError, httpx.HTTPError, RuntimeError, ValueError, TypeError) as exc:
                # Keep the street candidates if geocoding/spatial lookup is
                # unavailable, but expose why the exact address could not be
                # resolved instead of silently implying an exact match.
                for record in records:
                    record.attributes["spatial_lookup_status"] = "failed"
                    record.attributes["spatial_lookup_error"] = type(exc).__name__

        return records

    def _search_by_geocoded_point(
        self, request: SearchRequest, normalized: Any
    ) -> list[PropertyRecord]:
        if self._geocoder is None:
            cache_path = (
                Path.home()
                / ".imobhunter"
                / "cache"
                / "geosampa"
                / "address-geocoding.sqlite3"
            )
            self._geocoder = CachedAddressGeocoder(
                cache_path,
                "ImobHunter-BR/0.1.18 (GeoSampa address-to-parcel lookup)",
            )

        query = ", ".join(
            part
            for part in (
                normalized.normalized,
                request.city,
                request.state,
                "Brasil",
            )
            if part
        )
        geocoded = self._geocoder.geocode(query)
        latitude = float(geocoded["latitude"])
        longitude = float(geocoded["longitude"])
        import math

        lat_delta = 20.0 / 111_000.0
        lon_delta = 20.0 / (
            111_000.0 * max(abs(math.cos(math.radians(latitude))), 0.1)
        )
        params = {
            "service": "WFS",
            "version": "1.0.0",
            "request": "GetFeature",
            "typeName": self.layer,
            "outputFormat": "json",
            "srsName": "EPSG:4326",
            "bbox": (
                f"{longitude - lon_delta},{latitude - lat_delta},"
                f"{longitude + lon_delta},{latitude + lat_delta},EPSG:4326"
            ),
            "maxFeatures": 50,
        }
        client = self._client or httpx.Client(timeout=self.timeout)
        close_client = self._client is None
        try:
            response = client.get(self.endpoint, params=params, timeout=self.timeout)
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError("GeoSampa WFS bbox returned invalid JSON") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"GeoSampa spatial lookup failed: {exc}") from exc
        finally:
            if close_client:
                client.close()

        if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
            raise RuntimeError(
                "GeoSampa spatial lookup did not return a GeoJSON FeatureCollection"
            )

        candidates = self._parse_features(payload)
        for record in candidates:
            record.attributes["address_geocoding_provider"] = str(
                geocoded.get("provider") or "configured geocoder"
            )
            record.attributes["geocoded_address"] = str(
                geocoded.get("display_name") or query
            )
            record.attributes["geocoded_latitude"] = latitude
            record.attributes["geocoded_longitude"] = longitude
            record.attributes["spatial_lookup_status"] = "completed"

        matches = [
            record for record in candidates
            if self._geometry_contains_point(
                record.attributes.get("geometry_geojson"), longitude, latitude
            )
        ]
        if matches:
            for record in matches:
                record.attributes["house_number_match"] = "geocoded_spatial_match"
            return matches

        # A geocoded point can land just outside a cadastral polygon due to
        # address interpolation. Return only the nearest parcel as an explicit
        # candidate, not as a confirmed address match.
        candidates_with_coordinates = [
            record for record in candidates
            if record.latitude is not None and record.longitude is not None
        ]
        if not candidates_with_coordinates:
            return []
        nearest = min(
            candidates_with_coordinates,
            key=lambda record: (
                (float(record.longitude) - longitude) ** 2
                + (float(record.latitude) - latitude) ** 2
            ),
        )
        nearest.attributes["house_number_match"] = "geocoded_spatial_candidate"
        return [nearest]

    @staticmethod
    def _geometry_contains_point(
        geometry_json: Any, longitude: float, latitude: float
    ) -> bool:
        if not geometry_json:
            return False
        try:
            geometry = json.loads(geometry_json) if isinstance(geometry_json, str) else geometry_json
        except (TypeError, ValueError):
            return False

        def in_ring(ring: Any) -> bool:
            if not isinstance(ring, list) or len(ring) < 4:
                return False
            inside = False
            previous = ring[-1]
            for current in ring:
                if not (
                    isinstance(current, list) and len(current) >= 2
                    and isinstance(previous, list) and len(previous) >= 2
                ):
                    previous = current
                    continue
                x1, y1 = float(previous[0]), float(previous[1])
                x2, y2 = float(current[0]), float(current[1])
                if (y1 > latitude) != (y2 > latitude):
                    crossing_x = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
                    if longitude < crossing_x:
                        inside = not inside
                previous = current
            return inside

        def in_polygon(rings: Any) -> bool:
            if not isinstance(rings, list) or not rings or not in_ring(rings[0]):
                return False
            return not any(in_ring(hole) for hole in rings[1:])

        kind = geometry.get("type") if isinstance(geometry, dict) else None
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if kind == "Polygon":
            return in_polygon(coordinates)
        if kind == "MultiPolygon" and isinstance(coordinates, list):
            return any(in_polygon(polygon) for polygon in coordinates)
        return False

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
                        # Preserve every field returned by the official layer.
                        # The normalized fields below support common UI views;
                        # raw fields ensure the dossier does not discard data
                        # just because a field name is not yet mapped.
                        "source_attributes": properties,
                        "source_attribute_names": sorted(str(key) for key in properties),
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
                            "nr_numero_porta",
                            "nr_endereco",
                            "numero",
                            "nr_porta",
                            "numero_predial",
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
