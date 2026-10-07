import csv
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

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

    def status(self) -> SourceStatus:
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

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        request.validate()
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
