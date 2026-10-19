from __future__ import annotations

import hashlib
import json
import math
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from imobhunter.application.address_geocoding import CachedAddressGeocoder
from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus
from imobhunter.sources.base import SourceAdapter
from imobhunter.sources.inde import DEFAULT_INDE_CSW_ENDPOINT, INDECatalog, GeospatialService

USER_AGENT = "ImobHunter-BR/0.1.18 (national municipal cadastral discovery)"
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_FEATURES_PER_LAYER = 40
SEARCH_RADIUS_KM = 0.8
CADASTRAL_TERMS = (
    "lote", "lotes", "parcela", "parcelas", "quadra", "cadastro imobiliario",
    "cadastro imobiliário", "imobiliario", "imobiliário", "inscricao imobiliaria",
    "inscrição imobiliária", "iptu", "parcelamento do solo",
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(char for char in decomposed if not unicodedata.combining(char)).split())


def _official_endpoint(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").casefold()
    return parsed.scheme == "https" and (
        host.endswith((".gov.br", ".gov")) or host == "gov.br"
    )


def _wfs_endpoint(url: str | None) -> bool:
    if not _official_endpoint(url):
        return False
    parsed = urlparse(url or "")
    path = parsed.path.casefold()
    query = parsed.query.casefold().replace("%3d", "=")
    if any(token in path for token in ("/wms", "wmts")):
        return False
    return any(token in path for token in ("/wfs", "/ows", "geoserver")) or "service=wfs" in query


def _layer_candidates(xml_text: str) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError("O catálogo municipal retornou capabilities WFS inválido.") from exc
    layers = []
    for node in root.iter():
        if _local_name(node.tag) not in {"featuretype", "featuretypelist"}:
            continue
        if _local_name(node.tag) != "featuretype":
            continue
        values: dict[str, str] = {}
        for child in node:
            key = _local_name(child.tag)
            if key in {"name", "title"} and child.text:
                values[key] = child.text.strip()
        if not values.get("name"):
            continue
        text = f"{values['name']} {values.get('title', '')}".casefold()
        if any(term in text for term in CADASTRAL_TERMS):
            layers.append({"name": values["name"], "title": values.get("title", values["name"])})
    return layers[:4]


def _representative_point(geometry: Any) -> tuple[float | None, float | None]:
    if not isinstance(geometry, dict):
        return None, None
    coordinates = geometry.get("coordinates")
    points: list[tuple[float, float]] = []

    def walk(value: Any) -> None:
        if isinstance(value, (list, tuple)):
            if len(value) >= 2 and all(isinstance(part, (int, float)) for part in value[:2]):
                lon, lat = float(value[0]), float(value[1])
                if -180 <= lon <= 180 and -90 <= lat <= 90:
                    points.append((lon, lat))
                return
            for child in value:
                walk(child)

    walk(coordinates)
    if not points:
        return None, None
    if str(geometry.get("type", "")).casefold() == "point":
        lon, lat = points[0]
    else:
        lon = sum(point[0] for point in points) / len(points)
        lat = sum(point[1] for point in points) / len(points)
    return lat, lon


def _attribute(properties: dict[str, Any], *terms: str) -> Any:
    folded = {str(key).casefold().replace("_", "").replace(" ", ""): value for key, value in properties.items()}
    for term in terms:
        key = term.casefold().replace("_", "").replace(" ", "")
        value = folded.get(key)
        if value not in (None, ""):
            return value
    return None


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(str(value).replace(",", "."))
        return parsed if math.isfinite(parsed) and parsed >= 0 else None
    except (TypeError, ValueError):
        return None


class NationalMunicipalCadastreAdapter(SourceAdapter):
    """Discovers documented official municipal WFS services through INDE.

    Only HTTPS government endpoints and layers whose metadata indicates cadastral
    content are queried. Nearby features are marked as spatial candidates; no
    ownership, SQL/IPTU or exact-address match is inferred from a geometry.
    """

    source_id = "national_municipal_cadastre"
    name = "Cadastro municipal oficial — descoberta INDE"
    category = "municipal"

    def __init__(
        self,
        *,
        cache_dir: str | Path | None = None,
        csw_endpoint: str = DEFAULT_INDE_CSW_ENDPOINT,
        client: httpx.Client | None = None,
        geocoder: Any | None = None,
        max_services: int = 8,
    ) -> None:
        self.cache_dir = Path(cache_dir or (Path.home() / ".imobhunter" / "cache" / "municipal_cadastre"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.csw_endpoint = csw_endpoint
        self._client = client
        self._geocoder = geocoder
        self.max_services = max(1, min(max_services, 12))

    def status(self) -> SourceStatus:
        return SourceStatus(
            self.source_id,
            self.name,
            "available",
            "Descobre serviços WFS governamentais documentados no catálogo INDE. A cobertura depende de cada órgão publicar o cadastro; ausência de resultado não significa ausência de imóvel.",
        )

    def _http(self) -> tuple[httpx.Client, bool]:
        if self._client is not None:
            return self._client, False
        return httpx.Client(
            timeout=httpx.Timeout(18.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, application/xml"},
            follow_redirects=True,
        ), True

    def _geocode(self, request: SearchRequest) -> tuple[float, float] | None:
        if not request.address or not request.city or not request.state:
            return None
        if self._geocoder is None:
            self._geocoder = CachedAddressGeocoder(
                Path.home() / ".imobhunter" / "geocoding.sqlite3", USER_AGENT
            )
        query = ", ".join(part for part in (
            " ".join(part for part in (request.address, request.number) if part),
            request.city, request.state, "Brasil",
        ) if part)
        result = self._geocoder.geocode(query)
        return float(result["latitude"]), float(result["longitude"])

    def _discover(self, request: SearchRequest) -> list[GeospatialService]:
        key = hashlib.sha256(
            f"{request.city}|{request.state}".casefold().encode("utf-8")
        ).hexdigest()
        cache_path = self.cache_dir / f"inde-{key}.json"
        if cache_path.is_file() and time.time() - cache_path.stat().st_mtime < CACHE_TTL_SECONDS:
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                return [GeospatialService(**item) for item in payload]
            except (OSError, ValueError, TypeError):
                cache_path.unlink(missing_ok=True)

        client, owned = self._http()
        found: dict[str, GeospatialService] = {}
        queries = (request.city, f"{request.city} cadastro")
        try:
            for query in queries:
                try:
                    services = INDECatalog.search_remote(
                        query, self.csw_endpoint, client=client, max_records=50
                    )
                except (RuntimeError, ValueError, TypeError, httpx.HTTPError):
                    continue
                for service in services:
                    combined = " ".join((
                        service.title, service.provider or "", service.url or "",
                        " ".join(service.keywords),
                    )).casefold()
                    if not any(term in combined for term in CADASTRAL_TERMS):
                        continue
                    if service.service_type and service.service_type.upper() not in {"WFS", "OGC:API"}:
                        continue
                    if not _wfs_endpoint(service.url):
                        continue
                    folded_metadata = _fold(combined)
                    # Require the municipality and UF to avoid cross-city parcel matches.
                    if _fold(request.city) not in folded_metadata or _fold(request.state) not in folded_metadata:
                        continue
                    found[service.url or service.service_id] = service
                    if len(found) >= self.max_services:
                        break
                if len(found) >= self.max_services:
                    break
        finally:
            if owned:
                client.close()
        services = list(found.values())[:self.max_services]
        if services:
            try:
                cache_path.write_text(
                    json.dumps([service.__dict__ for service in services], ensure_ascii=False),
                    encoding="utf-8",
                )
            except OSError:
                pass
        return services

    def _get(self, endpoint: str, params: dict[str, Any]) -> httpx.Response:
        if not _official_endpoint(endpoint):
            raise ValueError("O endpoint cadastral precisa usar HTTPS e domínio governamental.")
        client, owned = self._http()
        try:
            response = client.get(endpoint, params=params)
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Falha no geosserviço municipal: {type(exc).__name__}.") from exc
        finally:
            if owned:
                client.close()

    def _layers(self, endpoint: str) -> list[dict[str, str]]:
        response = self._get(endpoint, {
            "service": "WFS", "version": "2.0.0", "request": "GetCapabilities",
        })
        return _layer_candidates(response.text)

    def _features(
        self, endpoint: str, layer: str, bbox: tuple[float, float, float, float]
    ) -> list[dict[str, Any]]:
        min_lon, min_lat, max_lon, max_lat = bbox
        response = self._get(endpoint, {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": layer, "outputFormat": "application/json",
            "srsName": "EPSG:4326",
            "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat},EPSG:4326",
            "count": MAX_FEATURES_PER_LAYER, "startIndex": 0,
        })
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("WFS cadastral oficial não retornou GeoJSON.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
            raise TypeError("WFS cadastral oficial retornou uma resposta GeoJSON inválida.")
        return [feature for feature in payload["features"] if isinstance(feature, dict)]

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        if not request.address or not request.city or not request.state:
            return []
        point = self._geocode(request)
        if point is None:
            return []
        latitude, longitude = point
        lat_delta = SEARCH_RADIUS_KM / 111.0
        lon_delta = SEARCH_RADIUS_KM / max(20.0, 111.0 * abs(math.cos(math.radians(latitude))))
        bbox = (longitude - lon_delta, latitude - lat_delta, longitude + lon_delta, latitude + lat_delta)

        records: list[PropertyRecord] = []
        for service in self._discover(request):
            endpoint = service.url or ""
            try:
                layers = self._layers(endpoint)
                for layer in layers:
                    for feature in self._features(endpoint, layer["name"], bbox):
                        properties = feature.get("properties") or {}
                        geometry = feature.get("geometry")
                        if not isinstance(properties, dict) or not isinstance(geometry, dict):
                            continue
                        lat, lon = _representative_point(geometry)
                        raw_id = feature.get("id") or _attribute(
                            properties, "id", "gid", "objectid", "codigo", "cod_lote", "id_lote"
                        )
                        block = _attribute(properties, "quadra", "numero_quadra", "cd_quadra", "quadra_fiscal")
                        lot = _attribute(properties, "lote", "numero_lote", "cd_lote")
                        area = _float(_attribute(properties, "area_m2", "area_terreno", "area_lote"))
                        safe_properties = {
                            str(key): value for key, value in properties.items()
                            if value is not None and len(str(value)) <= 500
                        }
                        records.append(PropertyRecord(
                            property_id=str(raw_id) if raw_id not in (None, "") else None,
                            address=str(_attribute(properties, "logradouro", "endereco", "nome_logradouro") or request.address),
                            city=request.city,
                            state=request.state,
                            block=str(block) if block not in (None, "") else None,
                            lot=str(lot) if lot not in (None, "") else None,
                            area_m2=area,
                            latitude=lat,
                            longitude=lon,
                            attributes={
                                "geometry_geojson": json.dumps(geometry, ensure_ascii=False),
                                "cadastre_match": "spatial_candidate_only",
                                "official_source": service.provider or service.title,
                                "service_title": service.title,
                                "service_url": endpoint,
                                "wfs_layer": layer["name"],
                                "source_properties": safe_properties,
                                "parcel_status": "returned_by_official_layer",
                                "sql_status": "not_provided_by_layer",
                                "iptu_status": "not_provided_by_layer",
                                "owner_status": "not_provided_by_layer",
                            },
                            provenance=(Provenance(
                                self.source_id, confidence=0.75,
                                reference=f"{service.service_id}:{layer['name']}:{raw_id or ''}",
                            ),),
                        ))
            except (RuntimeError, ValueError, TypeError, httpx.HTTPError):
                # A failed/unsupported municipal endpoint must not suppress other sources.
                continue
        return records
