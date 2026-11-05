"""Municipality-scoped user-added data sources for property prospecting.

WFS and ArcGIS reuse the existing municipal parcel parsers. Website-only
entries remain bookmarks; they cannot be mistaken for cadastral APIs.
"""
from __future__ import annotations

from dataclasses import replace
import json
from typing import Any

import certifi
import httpx

from imobhunter.application.cadastral_map import parse_geometry, valid_lon_lat
from imobhunter.application.sp_iptu_parquet import search_sp_iptu_sqlite
from imobhunter.application.custom_municipal_sources import (
    CustomMunicipalSource, CustomMunicipalStore, read_municipal_file,
    safe_public_url,
)
from imobhunter.domain.identity import canonical_text
from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus
from imobhunter.sources.base import SourceAdapter
from imobhunter.sources.official_municipal_services import OfficialMunicipalServicesAdapter
from imobhunter.sources.sp_mogi_cadastre import mogi_historical_file_record


def _normalized_fields(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        canonical_text(k).replace(" ", "_").casefold(): value
        for k, value in properties.items()
    }


def _first(fields: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = fields.get(name)
        if value not in (None, ""):
            return value
    return None


def _identifier_equal(a: Any, b: Any) -> bool:
    left, right = canonical_text(a), canonical_text(b)
    if left.isdecimal() and right.isdecimal():
        return (left.lstrip("0") or "0") == (right.lstrip("0") or "0")
    return bool(left) and left == right


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        raw = str(value).strip()
        if "," in raw and "." in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif "," in raw:
            raw = raw.replace(",", ".")
        return float(raw)
    except (ValueError, TypeError, OverflowError):
        return None


def _local_row(
    row: dict[str, Any], request: SearchRequest,
    source: CustomMunicipalSource,
) -> PropertyRecord | None:
    if row.get("type") == "Feature":
        properties = row.get("properties") or {}
        geometry = row.get("geometry")
        feature_id = row.get("id")
    else:
        properties = row
        geometry = row.get("geometry") or row.get("geometry_geojson")
        feature_id = None
    if not isinstance(properties, dict):
        return None
    f = _normalized_fields(properties)
    if (canonical_text(source.city) == "MOGI DAS CRUZES"
            and canonical_text(source.state) == "SP"
            and {"cadastro_id", "nro_local", "logradouro"}.issubset(f)):
        # The 2024 official municipal CSV is historical and may include
        # monetary/tributary columns. Keep only a safe cadastral projection.
        return mogi_historical_file_record(
            f, request, source.source_id, source.file_name or "arquivo autorizado"
        )
    row_city = _first(f, "municipio", "cidade", "city", "nm_municipio")
    row_state = _first(f, "uf", "estado", "state", "sigla_uf")
    # User catalog metadata never overrides a contradictory municipality/UF
    # explicitly present in the imported municipal file.
    if row_city and canonical_text(row_city) != canonical_text(source.city):
        return None
    if row_state and canonical_text(row_state) != canonical_text(source.state):
        return None
    street = _first(f, "logradouro", "endereco", "address", "rua", "nome_logradouro")
    number = _first(f, "numero", "numero_predial", "num_predial", "housenumber")
    block = _first(f, "quadra", "block", "quadra_fiscal", "cod_quadra")
    lot = _first(f, "lote", "lot", "lote_fiscal", "cod_lote")
    cib = _first(f, "cib", "codigo_cib")
    sql = _first(f, "sql", "iptu_registration_number", "inscricao_imobiliaria", "inscricao_iptu")
    if request.block and request.lot:
        match = _identifier_equal(block, request.block) and _identifier_equal(lot, request.lot)
    elif request.cib:
        match = _identifier_equal(cib, request.cib)
    elif request.address:
        expected = canonical_text(request.address)
        actual = canonical_text(street)
        # Match complete street/number only; never return an unrelated lot
        # merely because the address has the same street name.
        match = bool(actual and expected and (actual == expected or actual.startswith(expected + " ")))
        if request.number:
            match = match and _identifier_equal(number, request.number)
    else:
        match = False
    if not match:
        return None
    parsed_geometry = None
    if geometry:
        polygons, point = parse_geometry(geometry)
        if polygons or point:
            if isinstance(geometry, str):
                parsed_geometry = geometry
            elif isinstance(geometry, dict):
                parsed_geometry = json.dumps(geometry, ensure_ascii=False)
    coordinates = valid_lon_lat(
        _first(f, "longitude", "lon", "x"),
        _first(f, "latitude", "lat", "y"),
    )
    if coordinates is None and parsed_geometry:
        polygons, point = parse_geometry(parsed_geometry)
        if point:
            coordinates = point
        elif polygons:
            ring = polygons[0][0]
            coordinates = (
                (min(p[0] for p in ring) + max(p[0] for p in ring)) / 2,
                (min(p[1] for p in ring) + max(p[1] for p in ring)) / 2,
            )
    entry_id = _first(f, "property_id", "id_imovel", "id_lote", "id")
    attr: dict[str, Any] = {
        "source": source.source_id,
        "official_source": source.name,
        "imported_municipal_file": source.file_name,
        "source_properties": properties,
        "geometry_geojson": parsed_geometry,
        "sql": str(sql) if sql is not None else None,
        "iptu_registration_number": str(sql) if sql is not None else None,
        "sql_status": "provided_by_import" if sql is not None else "not_provided_by_import",
        "owner_status": "not_verified",
        "cadastre_match": "file_record_exact_fields" if number else "file_record_parcel_fields",
        "door_number": str(number) if number is not None else None,
    }
    street_and_number = (
        f"{street}, {number}" if street and number else str(street or request.address or "")
    )
    return PropertyRecord(
        property_id=str(entry_id or feature_id) if entry_id or feature_id else None,
        address=street_and_number,
        city=source.city, state=source.state,
        block=str(block) if block is not None else None,
        lot=str(lot) if lot is not None else None,
        cib=str(cib) if cib is not None else None,
        area_m2=_number(_first(f, "area_m2", "area_terreno", "area", "area_lote")),
        latitude=coordinates[1] if coordinates else None,
        longitude=coordinates[0] if coordinates else None,
        attributes=attr,
        provenance=(Provenance(source.source_id, confidence=0.8,
                               reference=f"arquivo local: {source.file_name}"),),
    )


class _AuthorizedRemote(OfficialMunicipalServicesAdapter):
    """Use existing GeoJSON cadastral parsing but with an authorized custom URL."""

    def _get(self, url: str, params: dict[str, Any]) -> httpx.Response:
        if not safe_public_url(url):
            raise ValueError("Serviço municipal precisa de HTTPS público, sem rede interna.")
        client, owned = self._http()
        try:
            response = client.get(url, params=params, follow_redirects=False)
            if 300 <= response.status_code < 400:
                raise ValueError("Redirecionamento bloqueado: confira o endpoint cadastral.")
            response.raise_for_status()
            return response
        finally:
            if owned:
                client.close()

    def _http(self) -> tuple[httpx.Client, bool]:
        if self._client is not None:
            return self._client, False
        return httpx.Client(
            verify=certifi.where(), timeout=httpx.Timeout(self.timeout, connect=5),
            follow_redirects=False,
            headers={"User-Agent": "ImobHunter-BR/2.0 custom-municipal-source"},
        ), True


class CustomMunicipalAdapter(SourceAdapter):
    category = "municipal"

    def __init__(
        self, source: CustomMunicipalSource,
        store: CustomMunicipalStore,
        remote: _AuthorizedRemote | None = None,
    ) -> None:
        self.definition = source
        self.store = store
        self.source_id = source.source_id
        self.name = f"{source.name} — {source.city}/{source.state}"
        self._remote = remote
        self.last_error: str | None = None

    def status(self) -> SourceStatus:
        local = self.store.local_path(self.definition)
        has_file = bool(local and local.is_file())
        has_api = self.definition.kind in {"wfs", "arcgis"} and self.definition.url
        if has_file or has_api:
            message = (
                f"{self.definition.city}/{self.definition.state}: "
                + ("arquivo municipal local; " if has_file else "")
                + ("endpoint API configurado (ainda não validado)" if has_api else "consulta local")
            )
            return SourceStatus(self.source_id, self.name, "configured", message)
        return SourceStatus(
            self.source_id, self.name, "not_configured",
            "Fonte salva como site/link; sem API cadastral consultável ou arquivo municipal importado.",
        )

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        if not self.definition.matches(request.city, request.state):
            return []
        records: list[PropertyRecord] = []
        data_path = self.store.local_path(self.definition)
        if data_path is not None:
            if not data_path.is_file():
                raise RuntimeError("Arquivo cadastral municipal não encontrado.")
            # Large São Paulo Parquet imports are indexed once in SQLite.
            # Never reload millions of records into memory on each search.
            rows = (
                search_sp_iptu_sqlite(data_path, request)
                if data_path.suffix.lower() == ".sqlite3"
                else read_municipal_file(data_path)
            )
            for row in rows:
                record = _local_row(row, request, self.definition)
                if record is not None:
                    records.append(record)
                    if len(records) >= 100:
                        break
        if self.definition.kind not in {"wfs", "arcgis"} or not self.definition.url:
            return records
        remote = self._remote
        if remote is None:
            remote = _AuthorizedRemote(timeout=12.0)
            self._remote = remote
        try:
            lat, lon = remote._geocode(request)
            if self.definition.kind == "wfs":
                live = remote._wfs_records(
                    self.definition.city, self.definition.state,
                    self.definition.url, lat, lon, request,
                )
            else:
                live = remote._arcgis_records(
                    self.definition.city, self.definition.state,
                    lat, lon, request, layer_url=self.definition.url,
                )
        except (httpx.HTTPError, OSError, RuntimeError, ValueError, TypeError) as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            if records:
                return records  # Preserve local matches even if remote is offline.
            raise RuntimeError(f"Fonte {self.name} indisponível: {self.last_error}") from exc
        self.last_error = None
        for rec in live:
            attrs = dict(rec.attributes)
            attrs.update({
                "source": self.source_id,
                "official_source": self.definition.name,
                "service_url": self.definition.url,
                "user_added_source": True,
            })
            records.append(replace(
                rec, city=self.definition.city, state=self.definition.state,
                attributes=attrs,
                provenance=(Provenance(
                    self.source_id, confidence=0.7,
                    reference=self.definition.url,
                ),),
            ))
        return records


def reload_custom_sources(registry: Any, store: CustomMunicipalStore) -> None:
    """Replace only user-added adapters in the live registry.

    SearchService takes registry snapshots when searches start. The next search
    sees the newly saved municipal source, including after app restart.
    """
    for key in tuple(registry._sources):
        if key.startswith("local_municipal_"):
            registry._sources.pop(key, None)
    for definition in store.list():
        registry.register(CustomMunicipalAdapter(definition, store))
