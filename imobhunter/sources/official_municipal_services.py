from __future__ import annotations

import json
import math
import ssl
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
        "url": "https://geoserver.praiagrande.sp.gov.br/ows",
    },
    ("belo horizonte", "mg"): {
        "city": "Belo Horizonte",
        "state": "MG",
        "url": "https://bhmap.pbh.gov.br/v2/api/idebhgeo/wfs",
    },
    ("santos", "sp"): {
        "city": "Santos",
        "state": "SP",
        "url": "https://egov.santos.sp.gov.br/geoserver/wfs",
    },
    ("bertioga", "sp"): {
        "city": "Bertioga",
        "state": "SP",
        "url": "https://geoportal.bertioga.sp.gov.br/geoserver/ows",
    },
}
RIO_ARCGIS_LAYER = (
    "https://pgeo3.rio.rj.gov.br/arcgis/rest/services/"
    "CadParcel/IMOVEIS_TERRITORIAIS/FeatureServer/0"
)
RIO_GEOPAL_LAYER = (
    "https://pgeo3.rio.rj.gov.br/arcgis/rest/services/"
    "CadParcel/GeoPAL/FeatureServer/0"
)
DF_ARCGIS_LAYER = (
    "https://www.geoservicos.ide.df.gov.br/arcgis/rest/services/"
    "Aplicacoes/CERTIDAO_IMOVEL/FeatureServer/0"
)
GOIANIA_ARCGIS_LAYER = (
    "https://portalmapa.goiania.go.gov.br/servicogyn/rest/services/"
    "MapaServer/Feature_Base/MapServer/3"
)
BLUMENAU_ARCGIS_LAYER = (
    "https://geo.blumenau.sc.gov.br/server/rest/services/"
    "Cadastro_Imobiliario/Lotes_Blumenau/FeatureServer/0"
)
RECIFE_CKAN_API = "https://dados.recife.pe.gov.br/api/3/action"
RECIFE_IPTU_DATASET_ID = "imposto-predial-e-territorial-urbano-iptu"
PORTO_ALEGRE_ARCGIS_LAYER = (
    "https://gis-smamus.portoalegre.rs.gov.br/server/rest/services/"
    "01_PUBLICACOES/dmweb_lotes_fiscais/MapServer/0"
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

    def priority(layer: dict[str, str]) -> int:
        name = _fold(layer["name"]).replace(" ", "").replace("_", "")
        # Fiscal parcels carry IPTU/launch attributes; query them before geometry-only layers.
        label = _fold(f"{layer['name']} {layer['title']}").replace(" ", "").replace("_", "")
        if any(term in label for term in ("sql", "inscricaoimobiliaria", "lotesfiscais", "geoimobiliario")):
            return 0
        if any(term in name for term in ("cadastroimobiliario", "imoveisterritoriais", "lotectm")):
            return 1
        # Aggregate lot layers must come after individual parcel layers.
        if name.endswith(":lotestotal"):
            return 3
        if "lotes" in name or "lote" in name:
            return 2
        if "loteamentoaprovado" in name:
            return 3
        if "quadra" in name:
            return 3
        return 4

    result.sort(key=priority)
    return result[:6]


def _first(properties: dict[str, Any], *names: str) -> Any:
    by_fold = {
        _fold(str(key)).replace("_", "").replace(" ", ""): value
        for key, value in properties.items()
    }
    for name in names:
        value = by_fold.get(_fold(name).replace("_", "").replace(" ", ""))
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

    Current direct integrations: Praia Grande/SP, Santos/SP and Bertioga/SP,
    Belo Horizonte/MG (WFS), Rio de Janeiro/RJ and Distrito Federal (ArcGIS REST),
    Goiânia/GO and Blumenau/SC (ArcGIS REST cadastral layers).
    São Paulo capital remains covered by GeoSampaAdapter. This is not nationwide coverage.
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
        self.last_geocoded: dict[str, dict[str, Any]] = {}

    def status(self) -> SourceStatus:
        detail = (
            "Integrações diretas configuradas para Praia Grande/SP, Belo Horizonte/MG, "
            "Rio de Janeiro/RJ, Distrito Federal, Goiânia/GO, Blumenau/SC, Recife/PE e Porto Alegre/RS; São Paulo capital usa GeoSampa. "
            "Cobertura, atributos e disponibilidade dependem da camada oficial."
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
            # Use the operating system trust store while still validating TLS. Some
            # municipal portals chain their certificates through system-installed CAs.
            verify=ssl.create_default_context(),
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
        self.last_geocoded[request.city] = {
            "query": query,
            "display_name": result.get("display_name"),
            "latitude": result.get("latitude"),
            "longitude": result.get("longitude"),
        }
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
            "geocoded_address": self.last_geocoded.get(city),
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
            layer_records: list[PropertyRecord] = []
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
                    properties, "sql", "cod_sql", "codigo_sql", "sq_l", "s_q_l",
                    "setor_quadra_lote", "nr_contribuinte", "inscricao_imobiliaria",
                    "inscricao_municipal", "insc_imob", "inscricao_cadastral",
                    "indice_cadastral", "geolot", "inscricao_do_lote", "lancamento",
                    "numero_lancamento",
                )
                cib = _first(properties, "cib", "cd_cib", "codigo_cib")
                top_id = _first(properties, "top_id", "topid", "id_lote")
                built_area = _area(_first(
                    properties, "area_construida", "area_construcao",
                    "vwSomaAreas_IPTU2026_total_const", "area_edificada",
                    "area_construida_total",
                ))
                block = _first(
                    properties, "quadra", "cd_quadra", "cd_quadra_fiscal",
                    "numero_quadra", "cod_quadra", "novins",
                )
                lot = _first(
                    properties, "lote", "cd_lote", "lote_fiscal", "nulotctm",
                    "numero_lote", "lotes",
                )
                area = _area(_first(
                    properties, "area_m2", "area_terreno", "area_lote",
                    "qt_area_terreno", "area_total_terreno", "area_lote_m2",
                    "area_terreno_m2", "area_total_do_terreno", "area_terreno",
                    "area_do_terreno", "area_total", "areaterreno", "area_ter",
                ))
                street = _first(
                    properties, "endereco", "logradouro", "nm_logradouro",
                    "nome_logradouro", "endereco_oficial", "endereco_iptu",
                    "endereco_local", "endereco_entrega", "local_do_imovel",
                )
                number = _first(properties, "numero_imovel", "numero", "numero_predial")
                address = str(street or request.address or "")
                if number not in (None, "") and str(number) not in address:
                    address = f"{address}, {number}" if address else str(number)
                layer_records.append(PropertyRecord(
                    property_id=str(feature.get("id") or top_id or sql or "") or None,
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
                        "top_id": str(top_id) if top_id not in (None, "") else None,
                        "built_area_m2": built_area,
                        "fiscal_status": _first(properties, "fiscal"),
                        "real_status": _first(properties, "real"),
                        "parcel_status": _first(properties, "situacao"),
                        "parcel_domain": _first(properties, "dominio"),
                        "parcel_type": _first(properties, "tipo", "tipo_do_lote"),
                        "tax_status": _first(properties, "tributo"),
                        "gabarito": _first(properties, "gabarito"),
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
                if len(layer_records) >= MAX_FEATURES:
                    diagnostic["records_capped"] = MAX_FEATURES
                    break
            if layer_records:
                # Prefer an official layer that actually returns an SQL/registration
                # value over nearby geometry-only layers that happen to be listed first.
                sql_records = [
                    record for record in layer_records
                    if (record.attributes or {}).get("sql")
                    or (record.attributes or {}).get("iptu_registration_number")
                ]
                if sql_records:
                    return sql_records[:MAX_FEATURES]
                if not records:
                    records.extend(layer_records[:MAX_FEATURES])
        return records

    def _arcgis_records(
        self, city: str, state: str, latitude: float, longitude: float,
        request: SearchRequest, *, layer_url: str = RIO_ARCGIS_LAYER,
    ) -> list[PropertyRecord]:
        url = layer_url + "/query"
        # Goiânia's ArcGIS 10.4 layer is stricter about the geometry payload:
        # include the point's spatial reference inside the geometry object as well
        # as the inSR query parameter. Keep all other municipalities unchanged.
        point_geometry = {"x": longitude, "y": latitude}
        if layer_url == GOIANIA_ARCGIS_LAYER:
            point_geometry["spatialReference"] = {"wkid": 4326}
        response = self._get(url, {
            "where": "1=1",
            "geometry": json.dumps(point_geometry),
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
        # Some ArcGIS municipal services reject distance-buffer queries despite
        # exposing a public layer. Retry the same point intersection without the
        # optional distance/units parameters before reporting a source failure.
        if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
            first_error = payload.get("error") if isinstance(payload, dict) else None
            fallback_params = {
                "where": "1=1",
                "geometry": json.dumps(point_geometry),
                "geometryType": "esriGeometryPoint",
                "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": 4326,
                "f": "json",
                "resultRecordCount": MAX_FEATURES,
            }
            fallback_payload = self._get(url, fallback_params).json()
            if isinstance(fallback_payload, dict) and isinstance(fallback_payload.get("features"), list):
                payload = fallback_payload
                self.last_diagnostics[city] = {
                    "endpoint": layer_url,
                    "query_fallback": "point_intersection_without_distance",
                    "initial_error": first_error,
                }
            elif layer_url == GOIANIA_ARCGIS_LAYER:
                # Goiânia's public layer can reject spatial filters with HTTP 400.
                # Fall back to a documented street-name attribute query, rather
                # than returning unrelated parcels or failing the whole lookup.
                street_tokens = [
                    token.upper()
                    for token in _fold(request.address or "").split()
                    if len(token) > 2
                    and token not in {
                        "avenida", "av", "rua", "travessa", "alameda",
                        "rodovia", "praca", "largo", "estrada",
                    }
                    and not token.isdigit()
                ]
                street_token = street_tokens[-1] if street_tokens else ""
                if street_token:
                    street_params = {
                        "where": f"nmlogradou LIKE '%{street_token.replace(chr(39), chr(39) * 2)}%'",
                        "outFields": "*",
                        "returnGeometry": "true",
                        "outSR": 4326,
                        "f": "json",
                        "resultRecordCount": MAX_FEATURES,
                    }
                    street_payload = self._get(url, street_params).json()
                else:
                    street_payload = None
                if isinstance(street_payload, dict) and isinstance(street_payload.get("features"), list):
                    payload = street_payload
                    self.last_diagnostics[city] = {
                        "endpoint": layer_url,
                        "query_fallback": "street_name_attribute_query",
                        "street_token": street_token,
                        "initial_error": first_error,
                        "spatial_fallback_error": (
                            fallback_payload.get("error")
                            if isinstance(fallback_payload, dict) else type(fallback_payload).__name__
                        ),
                    }
                else:
                    fallback_error = (
                        fallback_payload.get("error")
                        if isinstance(fallback_payload, dict) else type(fallback_payload).__name__
                    )
                    street_error = (
                        street_payload.get("error")
                        if isinstance(street_payload, dict) else type(street_payload).__name__
                    )
                    raise TypeError(
                        "ArcGIS REST municipal sem lista features; "
                        f"consulta inicial={first_error!r}; fallback={fallback_error!r}; "
                        f"consulta por logradouro={street_error!r}"
                    )
            else:
                fallback_error = (
                    fallback_payload.get("error")
                    if isinstance(fallback_payload, dict) else type(fallback_payload).__name__
                )
                raise TypeError(
                    "ArcGIS REST municipal sem lista features; "
                    f"consulta inicial={first_error!r}; fallback={fallback_error!r}"
                )
        self.last_diagnostics[city] = {
            **self.last_diagnostics.get(city, {}),
            "endpoint": layer_url,
            "geocoded_address": self.last_geocoded.get(city),
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
            sql = _first(
                properties, "inscricao_imobiliaria", "inscricao_cadastral", "cadastral",
                "iptu_imovel",
            )
            is_goiania = layer_url == GOIANIA_ARCGIS_LAYER
            is_blumenau = layer_url == BLUMENAU_ARCGIS_LAYER
            is_porto_alegre = layer_url == PORTO_ALEGRE_ARCGIS_LAYER
            cib = _first(properties, "cib", "cd_cib", "codigo_cib")
            block = _first(
                properties, "nrquadra", "quadra", "cod_quadra", "lt_quadra", "qtd"
            )
            lot = _first(
                properties, "nrlote", "numlote", "lote", "np", "chavegeo", "ch_lote", "lt_lote"
            )
            area = _area(_first(
                properties, "areaterr", "area_cartografica", "area_m2", "area_descrita", "shape_area",
                "shape__area", "iptu_area_terr",
            ))
            built_area = _area(_first(
                properties, "areaedif", "ac_area_ct", "area_construida", "area_construcao",
            ))
            street = _first(
                properties, "nmlogradou", "endereco", "logradouro", "endereco_completo",
                "iptu_endereco", "lt_endereco",
            )
            street_number = _first(properties, "nrimovel", "numero", "numero_imovel")
            address = (
                f"{street}, {street_number}"
                if street not in (None, "") and street_number not in (None, "")
                else street or request.address or ""
            )
            municipal_registration = _first(
                properties, "nrinscr", "inscricao_municipal", "inscricao_cadastral"
            ) if is_goiania else None
            parcel_identifier = (
                _first(properties, "id_lotes", "parcel_identifier") if is_porto_alegre
                else _first(properties, "iq", "parcel_identifier") if is_blumenau
                else None
            )
            if is_goiania:
                # nrinscr is retained as the source's registration field; do not
                # mislabel it as SQL/IPTU without an authoritative field definition.
                sql = _first(properties, "sql", "inscricao_sql", "codigo_sql")
            ciu = _first(properties, "iptu_ciu")
            registry_number = _first(properties, "matricula", "rgi")
            records.append(PropertyRecord(
                property_id=str(_first(properties, "objectid", "globalid", "chavegeo") or "") or None,
                registry_number=str(registry_number) if registry_number not in (None, "") else None,
                cib=str(cib) if cib not in (None, "") else None,
                address=str(address or request.address or ""),
                city=city, state=state,
                block=str(block) if block not in (None, "") else None,
                lot=str(lot) if lot not in (None, "") else None,
                area_m2=area, latitude=lat, longitude=lon,
                attributes={
                    "source": self.source_id,
                    "official_source": (
                        "Prefeitura de Goiânia — Cadastro Imobiliário"
                        if is_goiania
                        else "Prefeitura de Blumenau — Cadastro de Lotes"
                        if is_blumenau
                        else "Prefeitura de Porto Alegre — Lotes Fiscais (SMF/SMAMUS)"
                        if is_porto_alegre
                        else "IDE-DF — Lotes com Inscrição do IPTU"
                        if layer_url == DF_ARCGIS_LAYER
                        else "Prefeitura da Cidade do Rio de Janeiro — GeoPAL/IMOVEIS_TERRITORIAIS"
                    ),
                    "service_url": layer_url,
                    "service_type": "ArcGIS REST",
                    "geometry_geojson": json.dumps(geometry, ensure_ascii=False),
                    "source_properties": properties,
                    "built_area_m2": built_area,
                    "iptu_ciu": str(ciu) if ciu not in (None, "") else None,
                    "municipal_registration_number": (
                        str(municipal_registration)
                        if municipal_registration not in (None, "") else None
                    ),
                    "parcel_identifier": (
                        str(parcel_identifier) if parcel_identifier not in (None, "") else None
                    ),
                    "neighborhood": _first(properties, "nobairro", "bairro") if is_blumenau or is_porto_alegre else None,
                    "municipal_sector": (
                        str(_first(properties, "setor"))
                        if is_porto_alegre and _first(properties, "setor") not in (None, "")
                        else None
                    ),
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

    def _rio_geopal_records(
        self, latitude: float, longitude: float, request: SearchRequest,
    ) -> list[PropertyRecord]:
        """Secondary official Rio parcel source; provides parcel IDs, not IPTU SQL."""
        response = self._get(RIO_GEOPAL_LAYER + "/query", {
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
            raise TypeError("ArcGIS GeoPAL retornou JSON sem a lista features.")
        self.last_diagnostics["Rio de Janeiro — GeoPAL"] = {
            "endpoint": RIO_GEOPAL_LAYER,
            "feature_count": len(payload["features"]),
            "fields": sorted({
                str(key) for feature in payload["features"][:1]
                for key in (feature.get("attributes") or {})
            }),
            "purpose": "parcel identifiers only; not an IPTU SQL source",
        }
        records: list[PropertyRecord] = []
        for feature in payload["features"]:
            props = feature.get("attributes") or {}
            raw = feature.get("geometry") or {}
            if not props or not isinstance(raw, dict) or not {"x", "y"} <= raw.keys():
                continue
            geometry = {"type": "Point", "coordinates": [raw["x"], raw["y"]]}
            lat, lon = _lat_lon(geometry)
            block = _first(props, "quadra", "cod_quadra")
            lot = _first(props, "lote", "np", "chavegeo", "ch_lote")
            parcel_id = _first(props, "chavegeo", "cod_np", "objectid")
            records.append(PropertyRecord(
                property_id=str(parcel_id) if parcel_id not in (None, "") else None,
                address=request.address or "",
                city="Rio de Janeiro", state="RJ",
                block=str(block) if block not in (None, "") else None,
                lot=str(lot) if lot not in (None, "") else None,
                latitude=lat, longitude=lon,
                attributes={
                    "source": self.source_id,
                    "official_source": "Prefeitura do Rio — GeoPAL (parcelamento)",
                    "service_url": RIO_GEOPAL_LAYER,
                    "service_type": "ArcGIS REST",
                    "geometry_geojson": json.dumps(geometry, ensure_ascii=False),
                    "source_properties": props,
                    "parcel_identifier": str(parcel_id) if parcel_id not in (None, "") else None,
                    "sql": None,
                    "iptu_registration_number": None,
                    "sql_status": "not_provided_by_layer",
                    "iptu_status": "not_provided_by_layer",
                    "cadastre_match": "spatial_candidate_only",
                    "owner_status": "not_provided_by_layer",
                },
                provenance=(Provenance(
                    source_id=self.source_id, confidence=0.6,
                    reference=str(parcel_id or feature.get("id") or ""),
                ),),
            ))
        return records


    def _recife_records(self, request: SearchRequest) -> list[PropertyRecord]:
        """Search Recife's official IPTU open-data API when a resource is queryable.

        Public annual datasets do not guarantee a row-level datastore API or a
        spatial parcel layer, so availability and geometry are reported explicitly.
        """
        package_response = self._get(f"{RECIFE_CKAN_API}/package_show", {"id": RECIFE_IPTU_DATASET_ID})
        package_payload = package_response.json()
        package = package_payload.get("result") if isinstance(package_payload, dict) else None
        if not isinstance(package, dict) or not package_payload.get("success"):
            raise TypeError("Portal de dados do Recife não retornou metadados válidos do dataset IPTU.")
        resources = package.get("resources") or []
        queryable = [
            resource for resource in resources
            if isinstance(resource, dict) and resource.get("datastore_active") is True
        ]
        queryable.sort(key=lambda resource: (
            0 if "2026" in str(resource.get("name", "")) else
            1 if "2025" in str(resource.get("name", "")) else 2
        ))
        diagnostic: dict[str, Any] = {
            "endpoint": f"{RECIFE_CKAN_API}/package_show",
            "dataset_id": RECIFE_IPTU_DATASET_ID,
            "dataset_title": package.get("title"),
            "license_id": package.get("license_id"),
            "resource_count": len(resources),
            "queryable_resource_count": len(queryable),
            "query": request.address,
            "query_mode": "CKAN datastore full-text search",
            "geometry_available": False,
        }
        self.last_diagnostics["Recife"] = diagnostic
        if not queryable:
            diagnostic["result"] = "dataset_public_but_no_datastore_resource"
            diagnostic["resource_summary"] = [
                {"name": resource.get("name"), "format": resource.get("format"),
                 "datastore_active": resource.get("datastore_active"), "url": resource.get("url")}
                for resource in resources if isinstance(resource, dict)
            ][:30]
            return []
        query_text = " ".join(part for part in (request.address, request.number) if part).strip()
        if not query_text:
            return []
        all_rows: list[dict[str, Any]] = []
        used_resources: list[dict[str, Any]] = []
        for resource in queryable[:3]:
            response = self._get(f"{RECIFE_CKAN_API}/datastore_search", {
                "resource_id": resource.get("id"), "q": request.address or query_text,
                "limit": MAX_FEATURES,
            })
            payload = response.json()
            result = payload.get("result") if isinstance(payload, dict) else None
            if not isinstance(result, dict) or not payload.get("success"):
                continue
            rows = result.get("records")
            if isinstance(rows, list):
                all_rows.extend(row for row in rows if isinstance(row, dict))
                used_resources.append({
                    "id": resource.get("id"), "name": resource.get("name"),
                    "total": result.get("total"), "returned": len(rows),
                    "fields": [field.get("id") for field in result.get("fields", []) if isinstance(field, dict)],
                })
        diagnostic["resources_queried"] = used_resources
        diagnostic["record_count"] = len(all_rows)
        if not all_rows:
            diagnostic["result"] = "datastore_query_returned_no_rows"
            return []
        records: list[PropertyRecord] = []
        for index, properties in enumerate(all_rows[:MAX_FEATURES]):
            street = _first(properties, "logradouro", "nome_logradouro", "nm_logradouro",
                             "endereco", "endereco_imovel", "localizacao", "local_do_imovel")
            number = _first(properties, "numero", "numero_imovel", "numero_predial",
                            "num_imovel", "nr_imovel")
            address = str(street or request.address or "")
            if number not in (None, "") and str(number) not in address:
                address = f"{address}, {number}" if address else str(number)
            folded_street = _fold(str(street or ""))
            folded_query = _fold(request.address or "")
            folded_number = str(number or "").strip()
            exact_street = bool(folded_street and folded_query and
                                (folded_street == folded_query or folded_query in folded_street))
            exact_number = not request.number or (
                bool(folded_number) and folded_number == str(request.number).strip()
            )
            sql = _first(properties, "sql", "inscricao_sql", "sq_l", "s_q_l", "setor_quadra_lote")
            iptu_registration = _first(
                properties, "inscricao_iptu", "inscricao_imobiliaria", "inscricao_cadastral"
            )
            municipal_registration = _first(properties, "inscricao_municipal", "cadastro_municipal")
            area = _area(_first(properties, "area_terreno", "area_terreno_m2", "area_lote",
                                 "area_m2", "area_do_terreno", "area_total_terreno"))
            block = _first(properties, "quadra", "numero_quadra", "cod_quadra")
            lot = _first(properties, "lote", "numero_lote", "lote_fiscal")
            records.append(PropertyRecord(
                property_id=str(_first(properties, "id", "codigo_imovel", "cod_imovel",
                                        "sequencial", "inscricao") or f"recife-iptu-{index}"),
                address=address, city="Recife", state="PE",
                block=str(block) if block not in (None, "") else None,
                lot=str(lot) if lot not in (None, "") else None,
                area_m2=area, latitude=None, longitude=None,
                attributes={
                    "source": self.source_id,
                    "official_source": "Prefeitura do Recife — Portal de Dados Abertos / IPTU",
                    "service_url": f"{RECIFE_CKAN_API}/datastore_search",
                    "service_type": "CKAN Data API",
                    "dataset_id": RECIFE_IPTU_DATASET_ID,
                    "resource_id": used_resources[0]["id"] if used_resources else None,
                    "source_properties": properties,
                    "geometry_geojson": None,
                    "sql": str(sql) if sql not in (None, "") else None,
                    "iptu_registration_number": str(iptu_registration) if iptu_registration not in (None, "") else None,
                    "municipal_registration_number": str(municipal_registration) if municipal_registration not in (None, "") else None,
                    "sql_status": "provided_by_dataset" if sql not in (None, "") else "not_provided_by_dataset",
                    "iptu_status": "provided_by_dataset" if iptu_registration not in (None, "") else "not_provided_by_dataset",
                    "cadastre_match": "exact_address_match" if exact_street and exact_number else "dataset_text_search_candidate",
                    "address_match_note": "Correspondência textual conferida nos campos disponíveis; o recurso não fornece geometria.",
                    "owner_status": "not_inferred_from_taxpayer_fields",
                    "geometry_status": "not_provided_by_dataset",
                },
                provenance=(Provenance(
                    source_id=self.source_id, confidence=0.9 if exact_street and exact_number else 0.55,
                    reference=str(_first(properties, "id", "codigo_imovel", "cod_imovel", "sequencial") or ""),
                ),),
            ))
        diagnostic["result"] = "records_returned"
        diagnostic["returned_record_count"] = len(records)
        return records

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        if not request.city or not request.state:
            return []
        city_key, state_key = _fold(request.city), request.state.strip().casefold()
        if city_key in {"rio de janeiro", "rio"} and state_key in {"rj", "rio de janeiro"}:
            city, state, service_key = "Rio de Janeiro", "RJ", "rio"
            configured = None
        elif city_key in {"brasilia", "distrito federal", "df"} and state_key in {"df", "distrito federal", "brasilia"}:
            city, state, service_key = "Brasília", "DF", "df"
            configured = None
        elif city_key in {"goiania", "goiania (go)"} and state_key in {"go", "goias", "goiás"}:
            city, state, service_key = "Goiânia", "GO", "goiania"
            configured = None
        elif city_key == "blumenau" and state_key in {"sc", "santa catarina"}:
            city, state, service_key = "Blumenau", "SC", "blumenau"
            configured = None
        elif city_key in {"recife", "recife (pe)"} and state_key in {"pe", "pernambuco"}:
            city, state, service_key = "Recife", "PE", "recife"
            configured = None
        elif city_key in {"porto alegre", "porto alegre (rs)"} and state_key in {"rs", "rio grande do sul"}:
            city, state, service_key = "Porto Alegre", "RS", "porto_alegre"
            configured = None
        else:
            service_key = (city_key, state_key)
            configured = MUNICIPAL_WFS.get(service_key)
            if not configured:
                return []
            city, state = configured["city"], configured["state"]

        try:
            if service_key == "recife":
                records = self._recife_records(request)
                self.last_errors.pop(city, None)
                return records
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
                # Only fall back to GeoPAL when the individual territorial layer yields no features.
                # GeoPAL IDs/quadra/lote are not represented as IPTU SQL.
                if not records:
                    records = self._rio_geopal_records(latitude, longitude, request)
            elif service_key == "df":
                records = self._arcgis_records(
                    city, state, latitude, longitude, request, layer_url=DF_ARCGIS_LAYER
                )
            elif service_key == "goiania":
                records = self._arcgis_records(
                    city, state, latitude, longitude, request, layer_url=GOIANIA_ARCGIS_LAYER
                )
            elif service_key == "blumenau":
                records = self._arcgis_records(
                    city, state, latitude, longitude, request, layer_url=BLUMENAU_ARCGIS_LAYER
                )
            elif service_key == "porto_alegre":
                records = self._arcgis_records(
                    city, state, latitude, longitude, request, layer_url=PORTO_ALEGRE_ARCGIS_LAYER
                )
            else:
                records = self._wfs_records(
                    city, state, configured["url"], latitude, longitude, request
                )
            self.last_errors.pop(city, None)
            return records
        except (GeocodingError, httpx.HTTPError, ValueError, TypeError, RuntimeError, json.JSONDecodeError) as exc:
            self.last_errors[city] = f"{type(exc).__name__}: {str(exc)[:180]}"
            return []
