import csv
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

from imobhunter.application.address import normalize_request, normalize_text
from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus
from imobhunter.sources.base import SourceAdapter


_FIELD_ALIASES = {
    "cib": ("CIB", "CD_CIB", "CIB_IMOVEL", "CODIGO_CIB"),
    "address": ("ENDERECO", "DS_ENDERECO", "LOGRADOURO", "NM_LOGRADOURO"),
    "number": ("NUMERO", "NR_ENDERECO", "NUMERO_ENDERECO", "NR_IMOVEL"),
    "city": ("MUNICIPIO", "NM_MUNICIPIO", "NOME_MUNICIPIO"),
    "state": ("UF", "SIGLA_UF"),
    "block": ("QUADRA", "CD_QUADRA", "QUADRA_FISCAL"),
    "lot": ("LOTE", "CD_LOTE", "LOTE_FISCAL"),
    "area": ("AREA_M2", "AREA_TERRENO", "QT_AREA_TERRENO", "AREA"),
    "latitude": ("LATITUDE", "LAT"),
    "longitude": ("LONGITUDE", "LON", "LONG"),
}


def _pick(row: dict[str, Any], field: str) -> Any:
    normalized = {
        str(key).strip().upper().replace(" ", "_"): value for key, value in row.items()
    }
    for alias in _FIELD_ALIASES[field]:
        value = normalized.get(alias)
        if value not in (None, ""):
            return value
    return None


def _float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _rows_from_json(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
        for feature in payload.get("features", []):
            properties = dict(feature.get("properties") or {})
            geometry = feature.get("geometry") or {}
            coordinates = geometry.get("coordinates")
            if (
                geometry.get("type") == "Point"
                and isinstance(coordinates, list)
                and len(coordinates) >= 2
            ):
                properties.setdefault("LONGITUDE", coordinates[0])
                properties.setdefault("LATITUDE", coordinates[1])
            yield properties
    elif isinstance(payload, list):
        yield from payload
    else:
        raise ValueError("SINTER JSON must be a FeatureCollection or a list")


def _rows(path: Path) -> Iterable[dict[str, Any]]:
    if path.suffix.lower() in {".json", ".geojson"}:
        return _rows_from_json(path)
    if path.suffix.lower() == ".csv":
        def read_csv() -> Iterable[dict[str, Any]]:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                yield from csv.DictReader(handle)

        return read_csv()
    raise ValueError("SINTER file must be CSV, JSON or GeoJSON")


SINTER_API_BASE_ENV = "IMOBHUNTER_SINTER_API_BASE_URL"
SINTER_API_TOKEN_ENV = "IMOBHUNTER_SINTER_API_TOKEN"
SINTER_API_TIMEOUT_SECONDS = 20.0


def _remote_cib_record(payload: dict[str, Any], source_id: str) -> PropertyRecord:
    info = payload.get("InfoIbge") or {}
    cib_data = payload.get("Cib") or {}
    general = payload.get("DadosGeraisImovel") or {}
    address = payload.get("EnderecoImovel") or {}
    holders = payload.get("Titular") or []
    holder = holders[0] if isinstance(holders, list) and holders else {}
    cib = cib_data.get("valor")
    return PropertyRecord(
        cib=str(cib) if cib else None,
        address=str(address.get("nomeLogradouro")) if address.get("nomeLogradouro") else None,
        city=str(info.get("nomeMunicipio")) if info.get("nomeMunicipio") else None,
        state=str(info.get("siglaUf")) if info.get("siglaUf") else None,
        area_m2=_float(general.get("areaTerreno")),
        owner_name=str(holder.get("nomeTitular")) if holder.get("nomeTitular") else None,
        owner_document=str(holder.get("niTitular")) if holder.get("niTitular") else None,
        attributes={
            "source": "SINTER / CIB API",
            "situacao_cib": cib_data.get("situacao"),
            "inscricao_imobiliaria": general.get("inscricaoImobiliaria"),
            "area_construida_m2": general.get("areaConstruida"),
            "valor_venal": general.get("valorVenal"),
            "numero_imovel": address.get("numeroImovel"),
            "cep": address.get("cep"),
            "complemento": address.get("complEndereco"),
        },
        provenance=(Provenance(source_id, confidence=0.99, reference=str(cib) if cib else None),),
    )


class SINTERAdapter(SourceAdapter):
    """Reads an authorized SINTER/CIB export or local cache.

    The official SINTER APIs documented by Receita Federal are integration
    APIs for participating municipalities, not an anonymous public lookup API.
    Therefore this adapter deliberately consumes a local/exported dataset until
    an officially supported read API is exposed for third-party consumers.
    """

    source_id = "sinter_cib"
    name = "SINTER / CIB"
    category = "national_cadastre"

    def __init__(self, data_path: str | Path | None = None) -> None:
        configured = data_path or os.getenv("IMOBHUNTER_SINTER_CIB_PATH")
        self.data_path = Path(configured).expanduser() if configured else None
        self.api_base_url = os.getenv(SINTER_API_BASE_ENV, "").strip().rstrip("/")
        self.api_token = os.getenv(SINTER_API_TOKEN_ENV, "").strip()

    def status(self) -> SourceStatus:
        if self.api_base_url and self.api_token:
            return SourceStatus(self.source_id, self.name, "available", "SINTER API configured")
        if self.data_path is None:
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                "Configure IMOBHUNTER_SINTER_CIB_PATH with an authorized SINTER/CIB CSV/GeoJSON file.",
            )
        if not self.data_path.is_file():
            return SourceStatus(
                self.source_id,
                self.name,
                "error",
                f"SINTER/CIB file not found: {self.data_path}",
            )
        return SourceStatus(self.source_id, self.name, "available")

    def _search_remote_cib(self, cib: str) -> list[PropertyRecord]:
        url = f"{self.api_base_url}/api/v1/ui/{cib}"
        try:
            response = httpx.get(
                url,
                headers={"Authorization": f"Bearer {self.api_token}", "Accept": "application/json"},
                timeout=SINTER_API_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"SINTER API request failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("SINTER API returned an invalid payload")
        return [_remote_cib_record(payload, self.source_id)]

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        request.validate()
        if request.cib and self.api_base_url and self.api_token:
            return self._search_remote_cib(request.cib)
        status = self.status()
        if status.status != "available":
            raise RuntimeError(status.message or "SINTER/CIB source unavailable")

        normalized = normalize_request(request)
        wanted_street = normalize_text(normalized.street_name)
        wanted_number = normalize_text(normalized.number)
        wanted_city = normalize_text(normalized.city)
        wanted_state = normalize_text(normalized.state)
        wanted_block = normalize_text(request.block)
        wanted_lot = normalize_text(request.lot)

        records: list[PropertyRecord] = []
        for row in _rows(self.data_path):  # type: ignore[arg-type]
            row_city = normalize_text(str(_pick(row, "city") or ""))
            row_state = normalize_text(str(_pick(row, "state") or ""))
            if wanted_city and row_city and row_city != wanted_city:
                continue
            if wanted_state and row_state and row_state != wanted_state:
                continue

            row_block = normalize_text(str(_pick(row, "block") or ""))
            row_lot = normalize_text(str(_pick(row, "lot") or ""))

            if wanted_block and wanted_lot:
                if row_block != wanted_block or row_lot != wanted_lot:
                    continue
            elif wanted_street and wanted_number:
                row_address = normalize_text(str(_pick(row, "address") or ""))
                row_number = normalize_text(str(_pick(row, "number") or ""))
                if row_number != wanted_number:
                    continue
                if wanted_street and wanted_street not in (row_address or ""):
                    continue
            else:
                continue

            cib = _pick(row, "cib")
            records.append(
                PropertyRecord(
                    cib=str(cib) if cib is not None else None,
                    address=str(_pick(row, "address")) if _pick(row, "address") else None,
                    city=row_city or wanted_city,
                    state=row_state or wanted_state,
                    block=str(_pick(row, "block")) if _pick(row, "block") is not None else None,
                    lot=str(_pick(row, "lot")) if _pick(row, "lot") is not None else None,
                    area_m2=_float(_pick(row, "area")),
                    latitude=_float(_pick(row, "latitude")),
                    longitude=_float(_pick(row, "longitude")),
                    attributes={"source": "SINTER / CIB"},
                    provenance=(
                        Provenance(
                            self.source_id,
                            confidence=0.95,
                            reference=str(cib) if cib is not None else None,
                        ),
                    ),
                )
            )
        return records
