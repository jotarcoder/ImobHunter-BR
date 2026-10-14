from __future__ import annotations

import hashlib
import json
import math
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx

from imobhunter.application.address_geocoding import CachedAddressGeocoder
from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus
from imobhunter.sources.base import SourceAdapter

IPHAN_WFS = "https://geoserver.iphan.gov.br/geoserver/ows"
ICMBIO_WFS = "https://geoservicos.inde.gov.br/geoserver/ICMBio/ows"
USER_AGENT = "ImobHunter-BR/0.1.18 (official public geoservices)"
CACHE_TTL_SECONDS = 12 * 60 * 60
MAX_FEATURES_PER_LAYER = 200
SEARCH_RADIUS_KM = 2.5


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _feature_layers(xml_text: str) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError("O geosserviço retornou capabilities XML inválido.") from exc
    layers = []
    for node in root.iter():
        if _local_name(node.tag) != "featuretype":
            continue
        values = {}
        for child in node:
            key = _local_name(child.tag)
            if key in {"name", "title"} and child.text:
                values[key] = child.text.strip()
        if values.get("name"):
            layers.append({"name": values["name"], "title": values.get("title", values["name"])})
    return layers


def _coordinates(geometry: Any) -> tuple[float | None, float | None]:
    if not isinstance(geometry, dict):
        return None, None
    kind = str(geometry.get("type") or "").casefold()
    coordinates = geometry.get("coordinates")
    points: list[tuple[float, float]] = []

    def walk(value: Any) -> None:
        if isinstance(value, (list, tuple)):
            if len(value) >= 2 and all(isinstance(part, (int, float)) for part in value[:2]):
                lon, lat = float(value[0]), float(value[1])
                if -180 <= lon <= 180 and -90 <= lat <= 90:
                    points.append((lon, lat))
                return
            for part in value:
                walk(part)

    walk(coordinates)
    if not points:
        return None, None
    # A vertex-average is a stable fallback for display, not a cadastral centroid.
    longitude = sum(point[0] for point in points) / len(points)
    latitude = sum(point[1] for point in points) / len(points)
    if kind == "point":
        longitude, latitude = points[0]
    return latitude, longitude


class PublicGeoservicesAdapter(SourceAdapter):
    """Live nearby overlays from public IPHAN and ICMBio OGC WFS services.

    This adapter enriches an address search with nearby heritage/environmental
    features. It never infers ownership, registry number, tax status, or debt.
    """

    source_id = "official_geo_overlays"
    name = "Geosserviços oficiais — IPHAN / ICMBio"
    category = "heritage_environment"

    def __init__(
        self,
        *,
        cache_dir: str | Path | None = None,
        client: httpx.Client | None = None,
        geocoder: Any | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir or (Path.home() / ".imobhunter" / "cache" / "official_geo"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = client
        self._geocoder = geocoder

    def status(self) -> SourceStatus:
        return SourceStatus(
            self.source_id,
            self.name,
            "available",
            "Consulta online aos geosserviços públicos do IPHAN e ICMBio; exige endereço e cidade para delimitar a área próxima.",
        )

    def _http(self) -> tuple[httpx.Client, bool]:
        if self._client is not None:
            return self._client, False
        return httpx.Client(
            timeout=httpx.Timeout(25.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, application/xml"},
            follow_redirects=True,
        ), True

    def _cached_request(
        self, endpoint: str, params: dict[str, Any], *, xml: bool = False
    ) -> Any:
        key = hashlib.sha256(
            json.dumps({"endpoint": endpoint, "params": params}, sort_keys=True).encode()
        ).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if path.is_file() and time.time() - path.stat().st_mtime < CACHE_TTL_SECONDS:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                return payload["body"]
            except (OSError, ValueError, KeyError, TypeError):
                path.unlink(missing_ok=True)

        client, owned = self._http()
        try:
            response = client.get(endpoint, params=params)
            response.raise_for_status()
            body = response.text if xml else response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"Falha na consulta ao geosserviço oficial: {type(exc).__name__}.") from exc
        finally:
            if owned:
                client.close()
        temp = path.with_suffix(".json.part")
        try:
            temp.write_text(json.dumps({"body": body}, ensure_ascii=False), encoding="utf-8")
            temp.replace(path)
        except OSError:
            temp.unlink(missing_ok=True)
        return body

    def _layers(self, endpoint: str) -> list[dict[str, str]]:
        body = self._cached_request(
            endpoint,
            {"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"},
            xml=True,
        )
        return _feature_layers(str(body))

    @staticmethod
    def _select_layers(provider: str, layers: list[dict[str, str]]) -> list[str]:
        selected: list[str] = []
        for layer in layers:
            name = layer["name"]
            text = f"{name} {layer.get('title', '')}".casefold()
            if provider == "iphan":
                if any(term in text for term in ("bem_protecao", "bens materiais", "sitios", "sítios arqueolog")):
                    selected.append(name)
            elif provider == "icmbio":
                if "conserv" in text and ("unidade" in text or "uc_" in text or "uc " in text):
                    selected.append(name)
        return selected[:3]

    def _features(
        self, endpoint: str, layer: str, bbox: tuple[float, float, float, float]
    ) -> list[dict[str, Any]]:
        min_lon, min_lat, max_lon, max_lat = bbox
        payload = self._cached_request(
            endpoint,
            {
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeNames": layer,
                "outputFormat": "application/json",
                "srsName": "EPSG:4326",
                "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat},EPSG:4326",
                "count": MAX_FEATURES_PER_LAYER,
                "startIndex": 0,
            },
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
            raise RuntimeError(f"A camada {layer} não retornou uma FeatureCollection GeoJSON válida.")
        features = []
        for feature in payload["features"]:
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties") or {}
            if not isinstance(properties, dict):
                continue
            features.append({
                "layer": layer,
                "properties": properties,
                "geometry": feature.get("geometry"),
                "id": feature.get("id"),
            })
        return features

    def _geocode(self, request: SearchRequest) -> tuple[float, float] | None:
        if not request.address or not request.city or not request.state:
            return None
        if self._geocoder is None:
            self._geocoder = CachedAddressGeocoder(
                self.cache_dir / "address-geocoding.sqlite3",
                USER_AGENT,
            )
        query = ", ".join(
            part for part in (
                " ".join(part for part in (request.address, request.number) if part),
                request.city,
                request.state,
                "Brasil",
            ) if part
        )
        result = self._geocoder.geocode(query)
        return float(result["latitude"]), float(result["longitude"])

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        point = self._geocode(request)
        if point is None:
            return []
        latitude, longitude = point
        lat_delta = SEARCH_RADIUS_KM / 111.0
        lon_delta = SEARCH_RADIUS_KM / max(20.0, 111.0 * abs(math.cos(math.radians(latitude))))
        bbox = (
            max(-180.0, longitude - lon_delta),
            max(-90.0, latitude - lat_delta),
            min(180.0, longitude + lon_delta),
            min(90.0, latitude + lat_delta),
        )

        records: list[PropertyRecord] = []
        endpoints = (("iphan", IPHAN_WFS), ("icmbio", ICMBIO_WFS))
        for provider, endpoint in endpoints:
            layers = self._select_layers(provider, self._layers(endpoint))
            for layer in layers:
                for feature in self._features(endpoint, layer, bbox):
                    properties = feature["properties"]
                    lowered = {str(key).casefold(): value for key, value in properties.items()}
                    name = next(
                        (str(lowered[key]).strip() for key in (
                            "nome", "nome_bem", "nome_uc", "nome_unidade", "name",
                            "denominacao", "ds_nome", "nm_bem", "nm_uc",
                        ) if lowered.get(key) not in (None, "")),
                        layer,
                    )
                    feature_id = str(
                        feature.get("id")
                        or next((lowered[key] for key in (
                            "id", "gid", "objectid", "codigo", "co_iphan", "id_bem", "cod_uc",
                        ) if lowered.get(key) not in (None, "")), "")
                        or ""
                    )
                    lat, lon = _coordinates(feature.get("geometry"))
                    selected_attributes = {
                        key: value for key, value in properties.items()
                        if value not in (None, "") and len(str(value)) <= 500
                    }
                    selected_attributes.update({
                        "overlay_type": "heritage" if provider == "iphan" else "conservation_unit",
                        "layer": layer,
                        "official_source": "IPHAN" if provider == "iphan" else "ICMBio / INDE",
                        "source_url": endpoint,
                        "distance_note": "Feature intersecta a área de busca de aproximadamente 2,5 km; não representa limite jurídico do imóvel.",
                    })
                    records.append(PropertyRecord(
                        property_id=feature_id or None,
                        address=name,
                        city=request.city,
                        state=request.state,
                        latitude=lat,
                        longitude=lon,
                        attributes=selected_attributes,
                        provenance=(Provenance(
                            self.source_id,
                            confidence=0.82,
                            reference=f"{layer}:{feature_id}" if feature_id else layer,
                        ),),
                    ))
        return records
