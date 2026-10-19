from __future__ import annotations

import json
import math
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from imobhunter.application.address_geocoding import CachedAddressGeocoder, GeocodingError
from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus
from imobhunter.sources.base import SourceAdapter

# Endpoints are taken from municipal portals. They are not proxies and are queried
# directly; the adapter does not infer fiscal identifiers or ownership.
MUNICIPAL_WFS = {
    ("praia grande", "sp"): {
        "city": "Praia Grande",
        "state": "SP",
        "url": "https://geoserver.praiagrande.sp.gov.br/PraiaGrandePlantaCadastral/wfs",
    },
    ("belo horizonte", "mg"): {
        "city": "Belo Horizonte",
        "state": "MG",
        "url": "https://bhmap.pbh.gov.br/v2/api/idebhgeo/wfs",
    },
}
RIO_ARCGIS_LAYER = (
    "https://pgeo3.rio.rj.gov.br/arcgis/rest/services/"
    "CadParcel/IMOVEIS_TERRITORIAIS/FeatureServer/0"
)
CADASTRAL_TERMS = (
    "lote", "lotes", "parcela", "parcelas", "quadra", "imobiliario",
    "imobiliário", "iptu", "inscricao_imobiliaria", "inscrição imobiliária",
    "territorial", "parcelamento", "imoveis_territoriais", "imóveis territoriais",
)
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_FEATURES = 40


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        "".join(char for char in decomposed if not unicodedata.combining(char)).split()
    )


def _official_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    return parsed.scheme == "https" and (
        host.endswith(".gov.br") or host == "gov.br"
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _all_wfs_layers(xml_text: str) -> list[dict[str, str]]:
    root = ET.fromstring(xml_text)
    result = []
    for node in root.iter():
        if _local_name(node.tag) != "featuretype":
            continue
        values = {}
        for child in node:
            key = _local_name(child.tag)
            if key in {"name", "title"} and child.text:
                values[key] = child.text.strip()
        if values.get("name"):
            result.append({"name": values["name"], "title": values.get("title", values["name"])})
    return result


def _cadastral_layers(xml_text: str) -> list[dict[str, str]]:
    layers = _all_wfs_layers(xml_text)
    result = []
    for layer in layers:
        label = f"{layer['name']} {layer['title']}".casefold()
        if any(term in label for term in CADASTRAL_TERMS):
            result.append(layer)
    return result[:6]


def _first(properties: dict[str, Any], *names: str) -> Any:
    by_fold = {
        str(key).casefold().replace("_", "").replace(" ", ""): value
        for key, value in properties.items()
    }
    for name in names:
        value = by_fold.get(name.casefold().replace("_", "").replace(" ", ""))
        if value not in (None, "") and str(value).strip() not in {"-", "—"}:
            return value
    return None


def _area(value: Any) -> float | None:
    try:
        parsed = float(str(value).replace(",", "."))
        return parsed if math.isfinite(parsed) and parsed >= 0 else None
    except (TypeError, ValueError):
        return None


def _lat_lon(geometry: dict[str, Any]) -> tuple[float | None, float | None]:
    kind = str(geometry.get("type", "")).casefold()
    coords = geometry.get("coordinates")
    if kind == "point" and isinstance(coords, list) and len(coords) >= 2:
        return float(coords[1]), float(coords[0])
    points: list[tuple[float, float]] = []

    def walk(item: Any) -> None:
        if isinstance(item, (list, tuple)):
            if len(item) >= 2 and isinstance(item[0], (int, float)) and isinstance(item[1], (int, float)):
                points.append((float(item[0]), float(item[1])))
                return
            for child in item:
                walk(child)

    walk(coords)
    if not points:
        return None, None
    return (
        sum(point[1] for point in points) / len(points),
        sum(point[0] for point in points) / len(points),
    )


class OfficialMunicipalServicesAdapter(SourceAdapter):
    """Direct integrations for documented municipal parcel services.

    Current direct integrations: Praia Grande/SP (WFS), Belo Horizonte/MG (WFS),
    and Rio de Janeiro/RJ (ArcGIS REST). São Paulo capital remains covered by
    GeoSampaAdapter. This is not a claim of nationwide municipal coverage.
    """

    source_id = "official_municipal_services"
    name = "Cadastros municipais oficiais — WFS/ArcGIS"
    category = "municipal"

    def __init__(
        self,
        *,
        cache_dir: str | Path | None = None,
        client: httpx.Client | None = None,
        geocoder: Any | None = None,
        timeout: float = 18.0,
    ) -> None:
        self.cache_dir = Path(
            cache_dir or (Path.home() / ".imobhunter" / "cache" / "official_municipal")
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = client
        self._geocoder = geocoder
        self.timeout = timeout
        self.last_errors: dict[str, str] = {}
        self.last_diagnostics: dict[str, dict[str, Any]] = {}

    def status(self) -> SourceStatus:
        detail = (
            "Integrações diretas configuradas para Praia Grande/SP, Belo Horizonte/MG "
            "e Rio de Janeiro/RJ; São Paulo capital usa GeoSampa. Cobertura, atributos "
            "e disponibilidade dependem da camada oficial de cada município."
        )
        if self.last_errors:
            detail += " Últimas falhas: " + "; ".join(
                f"{city}: {error}" for city, error in self.last_errors.items()
            )
        if self.last_diagnostics:
            detail += " Diagnóstico recente: " + json.dumps(
                self.last_diagnostics, ensure_ascii=False
            )[:700]
        return SourceStatus(self.source_id, self.name, "available", detail)

    def _http(self) -> tuple[httpx.Client, bool]:
        if self._client is not None:
            return self._client, False
        return httpx.Client(
            timeout=httpx.Timeout(self.timeout),
            headers={"User-Agent": "ImobHunter-BR/0.1.19 municipal-cadastre"},
            follow_redirects=True,
        ), True

    def _get(self, url: str, params: dict[str, Any]) -> httpx.Response:
        if not _official_url(url):
            raise ValueError("Endpoint municipal precisa usar HTTPS em domínio governamental.")
        client, owned = self._http()
        try:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response
        finally:
            if owned:
                client.close()

    def _geocode(self, request: SearchRequest) -> tuple[float, float]:
        if self._geocoder is None:
            self._geocoder = CachedAddressGeocoder(
                Path.home() / ".imobhunter" / "geocoding.sqlite3",
                "ImobHunter-BR/0.1.19 (official municipal parcel lookup)",
            )
        query = ", ".join(
            part for part in (
                " ".join(part for part in (request.address, request.number) if part),
                request.city, request.state, "Brasil",
            ) if part
        )
        result = self._geocoder.geocode(query)
        return float(result["latitude"]), float(result["longitude"])

    @staticmethod
    def _bbox(latitude: float, longitude: float, radius_km: float = 0.8) -> str:
        lat_delta = radius_km / 111.0
        lon_delta = radius_km / max(20.0, 111.0 * abs(math.cos(math.radians(latitude))))
        return (
            f"{longitude - lon_delta},{latitude - lat_delta},"
            f"{longitude + lon_delta},{latitude + lat_delta},EPSG:4326"
        )

    def _wfs_records(
        self, city: str, state: str, endpoint: str, latitude: float, longitude: float,
        request: SearchRequest,
    ) -> list[PropertyRecord]:
        capabilities = self._get(endpoint, {
            "service": "WFS", "version": "2.0.0", "request": "GetCapabilities",
        })
        all_layers = _all_wfs_layers(capabilities.text)
        layers = _cadastral_layers(capabilities.text)
        diagnostic: dict[str, Any] = {
            "endpoint": endpoint,
            "capabilities_layer_count": len(all_layers),
            "capabilities_layers": [
                {"name": layer["name"], "title": layer["title"]}
                for layer in all_layers[:80]
            ],
            "layers_found": [layer["name"] for layer in layers],
            "queries": [],
        }
        self.last_diagnostics[city] = diagnostic
        records: list[PropertyRecord] = []
        for layer in layers:
            response = self._get(endpoint, {
                "service": "WFS", "version": "2.0.0", "request": "GetFeature",
                "typeNames": layer["name"], "outputFormat": "application/json",
                "srsName": "EPSG:4326", "bbox": self._bbox(latitude, longitude),
                "count": MAX_FEATURES, "startIndex": 0,
            })
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
                diagnostic["queries"].append({"layer": layer["name"], "error": "invalid_feature_collection"})
                continue
            diagnostic["queries"].append({
                "layer": layer["name"],
                "feature_count": len(payload["features"]),
                "fields": sorted({
                    str(key)
                    for feature in payload["features"][:1]
                    for key in (feature.get("properties") or {})
                }),
            })
            for feature in payload["features"]:
                properties = feature.get("properties") or {}
                geometry = feature.get("geometry")
                if not isinstance(properties, dict) or not isinstance(geometry, dict):
                    continue
                lat, lon = _lat_lon(geometry)
                sql = _first(
                    properties, "sql", "nr_contribuinte", "inscricao_imobiliaria",
                    "inscricao_cadastral", "indice_cadastral", "indice_cadastral",
                    "lancamento",
                )
                cib = _first(properties, "cib", "cd_cib", "codigo_cib")
                block = _first(
                    properties, "quadra", "cd_quadra", "cd_quadra_fiscal",
                    "numero_quadra", "cod_quadra",
                )
                lot = _first(
                    properties, "lote", "cd_lote", "lote_fiscal", "nulotctm",
                )
                area = _area(_first(
                    properties, "area_m2", "area_terreno", "area_lote",
                    "qt_area_terreno", "area_total_terreno",
                ))
                street = _first(
                    properties, "endereco", "logradouro", "nm_logradouro",
                    "nome_logradouro", "endereco_oficial", "endereco_iptu",
                )
                number = _first(properties, "numero_imovel", "numero", "numero_predial")
                address = str(street or request.address or "")
                if number not in (None, "") and str(number) not in address:
                    address = f"{address}, {number}" if address else str(number)
                records.append(PropertyRecord(
                    property_id=str(feature.get("id") or sql or "") or None,
                    cib=str(cib) if cib not in (None, "") else None,
                    address=address,
                    city=city, state=state,
                    block=str(block) if block not in (None, "") else None,
                    lot=str(lot) if lot not in (None, "") else None,
                    area_m2=area, latitude=lat, longitude=lon,
                    attributes={
                        "source": self.source_id,
                        "official_source": city,
                        "service_url": endpoint,
                        "service_type": "WFS",
                        "wfs_layer": layer["name"],
                        "geometry_geojson": json.dumps(geometry, ensure_ascii=False),
                        "source_properties": properties,
                        "sql": str(sql) if sql not in (None, "") else None,
                        "iptu_registration_number": str(sql) if sql not in (None, "") else None,
                        "sql_status": "provided_by_layer" if sql not in (None, "") else "not_provided_by_layer",
                        "iptu_status": "provided_by_layer" if sql not in (None, "") else "not_provided_by_layer",
                        "cadastre_match": "spatial_candidate_only",
                        "owner_status": "not_provided_by_layer",
                    },
                    provenance=(Provenance(
                        source_id=self.source_id, confidence=0.8, reference=str(sql or feature.get("id") or ""),
                    ),),
                ))
                if len(records) >= MAX_FEATURES:
                    diagnostic["records_capped"] = MAX_FEATURES
                    return records[:MAX_FEATURES]
        return records

    def _arcgis_records(
        self, city: str, state: str, latitude: float, longitude: float,
        request: SearchRequest,
    ) -> list[PropertyRecord]:
        url = RIO_ARCGIS_LAYER + "/query"
        response = self._get(url, {
            "where": "1=1",
            "geometry": json.dumps({"x": longitude, "y": latitude}),
            "geometryType": "esriGeometryPoint",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "distance": 800,
            "units": "esriSRUnit_Meter",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": 4326,
            "f": "json",
            "resultRecordCount": MAX_FEATURES,
        })
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
            raise TypeError("ArcGIS REST municipal retornou JSON sem a lista features.")
        self.last_diagnostics[city] = {
            "endpoint": RIO_ARCGIS_LAYER,
            "feature_count": len(payload["features"]),
            "fields": sorted({
                str(key)
                for feature in payload["features"][:1]
                for key in (feature.get("attributes") or {})
            }),
        }
        records: list[PropertyRecord] = []
        for feature in payload["features"]:
            properties = feature.get("attributes") or {}
            raw_geometry = feature.get("geometry") or {}
            rings = raw_geometry.get("rings")
            if isinstance(rings, list):
                geometry = {"type": "Polygon", "coordinates": rings}
            elif "x" in raw_geometry and "y" in raw_geometry:
                geometry = {"type": "Point", "coordinates": [raw_geometry["x"], raw_geometry["y"]]}
            else:
                geometry = {}
            if not properties or not geometry:
                continue
            lat, lon = _lat_lon(geometry)
            sql = _first(properties, "inscricao_imobiliaria", "inscricao_cadastral", "cadastral")
            cib = _first(properties, "cib", "cd_cib", "codigo_cib")
            block = _first(properties, "quadra", "cod_quadra")
            lot = _first(properties, "lote", "np", "chavegeo", "ch_lote")
            area = _area(_first(
                properties, "area_m2", "area_descrita", "shape_area", "shape__area",
            ))
            registry_number = _first(properties, "matricula", "rgi")
            records.append(PropertyRecord(
                property_id=str(_first(properties, "objectid", "globalid", "chavegeo") or "") or None,
                registry_number=str(registry_number) if registry_number not in (None, "") else None,
                cib=str(cib) if cib not in (None, "") else None,
                address=str(_first(properties, "endereco", "logradouro", "endereco_completo") or request.address or ""),
                city=city, state=state,
                block=str(block) if block not in (None, "") else None,
                lot=str(lot) if lot not in (None, "") else None,
                area_m2=area, latitude=lat, longitude=lon,
                attributes={
                    "source": self.source_id,
                    "official_source": "Prefeitura da Cidade do Rio de Janeiro — GeoPAL/IMOVEIS_TERRITORIAIS",
                    "service_url": RIO_ARCGIS_LAYER,
                    "service_type": "ArcGIS REST",
                    "geometry_geojson": json.dumps(geometry, ensure_ascii=False),
                    "source_properties": properties,
                    "sql": str(sql) if sql not in (None, "") else None,
                    "iptu_registration_number": str(sql) if sql not in (None, "") else None,
                    "sql_status": "provided_by_layer" if sql not in (None, "") else "not_provided_by_layer",
                    "iptu_status": "provided_by_layer" if sql not in (None, "") else "not_provided_by_layer",
                    "cadastre_match": "spatial_candidate_only",
                    "owner_status": "not_provided_by_layer",
                },
                provenance=(Provenance(
                    source_id=self.source_id, confidence=0.8, reference=str(sql or feature.get("id") or ""),
                ),),
            ))
        return records

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        if not request.city or not request.state:
            return []
        city_key, state_key = _fold(request.city), request.state.strip().casefold()
        if city_key in {"rio de janeiro", "rio"} and state_key in {"rj", "rio de janeiro"}:
            city, state, service_key = "Rio de Janeiro", "RJ", "rio"
        else:
            service_key = (city_key, state_key)
            configured = MUNICIPAL_WFS.get(service_key)
            if not configured:
                return []
            city, state = configured["city"], configured["state"]

        try:
            if request.address:
                latitude, longitude = self._geocode(request)
            elif request.block and request.lot:
                # Direct identifier lookups are currently supported by the WFS adapter
                # only where the service's field names are known.
                return []
            else:
                return []
            if service_key == "rio":
                records = self._arcgis_records(city, state, latitude, longitude, request)
            else:
                records = self._wfs_records(
                    city, state, configured["url"], latitude, longitude, request
                )
            self.last_errors.pop(city, None)
            return records
        except (GeocodingError, httpx.HTTPError, ValueError, TypeError, RuntimeError, json.JSONDecodeError) as exc:
            self.last_errors[city] = f"{type(exc).__name__}: {str(exc)[:180]}"
            return []
