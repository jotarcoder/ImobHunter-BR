from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus

from .base import SourceAdapter


class SIGEFAdapter(SourceAdapter):
    """Reads authorized SIGEF parcel data for rural-property enrichment.

    The official SIGEFGEO API is available through Conecta gov.br and
    requires consumer onboarding/credentials. This adapter accepts an
    authorized local export/cache until runtime credentials are configured.
    """

    source_id = "sigef"
    name = "INCRA / SIGEF"
    category = "rural"

    def __init__(self, data_path: str | Path | None = None) -> None:
        configured = data_path or os.getenv("IMOBHUNTER_SIGEF_PATH")
        self.data_path = Path(configured) if configured else None

    def status(self) -> SourceStatus:
        if not self.data_path:
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                "SIGEF requires authorized Conecta access or a local export/cache.",
            )
        if not self.data_path.exists():
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                f"SIGEF data file not found: {self.data_path}",
            )
        return SourceStatus(self.source_id, self.name, "configured")

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        rows = self._load()
        address = " ".join(
            part for part in (request.address, request.number) if part
        ).casefold()
        city = (request.city or "").casefold()
        state = (request.state or "").casefold()
        block = (request.block or "").casefold()
        lot = (request.lot or "").casefold()

        records: list[PropertyRecord] = []
        for row in rows:
            location = str(
                row.get("endereco")
                or row.get("localizacao")
                or row.get("address")
                or ""
            )
            row_city = str(row.get("municipio") or row.get("city") or "").casefold()
            row_state = str(row.get("uf") or row.get("state") or "").casefold()
            row_block = str(row.get("quadra") or row.get("block") or "").casefold()
            row_lot = str(row.get("lote") or row.get("lot") or "").casefold()

            if address and address not in location.casefold():
                continue
            if city and row_city and row_city != city:
                continue
            if state and row_state and row_state != state:
                continue
            if block and row_block and row_block != block:
                continue
            if lot and row_lot and row_lot != lot:
                continue

            records.append(self._to_record(row))
        return records

    def _load(self) -> list[dict[str, Any]]:
        if not self.data_path:
            return []
        if not self.data_path.exists():
            raise RuntimeError(f"SIGEF data file not found: {self.data_path}")

        suffix = self.data_path.suffix.lower()
        if suffix == ".csv":
            with self.data_path.open("r", encoding="utf-8-sig", newline="") as handle:
                return list(csv.DictReader(handle))

        if suffix in {".json", ".geojson"}:
            payload = json.loads(self.data_path.read_text(encoding="utf-8"))
            if suffix == ".geojson" or (
                isinstance(payload, dict) and payload.get("type") == "FeatureCollection"
            ):
                features = payload.get("features", [])
                if not isinstance(features, list):
                    raise ValueError("SIGEF GeoJSON features must be a list")
                rows: list[dict[str, Any]] = []
                for feature in features:
                    if not isinstance(feature, dict):
                        continue
                    properties = feature.get("properties") or {}
                    if not isinstance(properties, dict):
                        continue
                    row = dict(properties)
                    if feature.get("geometry") is not None:
                        row["_geometry"] = feature["geometry"]
                    rows.append(row)
                return rows

            rows = payload.get("parcelas", payload) if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                raise ValueError("SIGEF JSON must contain a list of parcels")
            return rows

        raise ValueError("SIGEF data must be CSV, JSON or GeoJSON")

    @staticmethod
    def _to_record(row: dict[str, Any]) -> PropertyRecord:
        area = row.get("areaHectares") or row.get("area_hectares") or row.get("area")
        area_m2 = float(area) * 10000 if area not in (None, "") else None
        code = str(
            row.get("parcelaCodigo")
            or row.get("parcela_codigo")
            or row.get("codigoImovel")
            or row.get("codigo_imovel")
            or ""
        ) or None

        attributes = {
            key: row.get(key)
            for key in (
                "id",
                "rt",
                "art",
                "situacaoInformada",
                "transcricao",
                "idEnvio",
                "tipoEnvio",
                "orgao",
                "dataSubmissao",
                "dataAprovacao",
                "status",
                "nomeArea",
                "natureza",
                "registroCns",
                "registroMatricula",
                "registroData",
                "sr",
                "detentorNome",
                "detentorCpf",
                "detentorCnpj",
                "titularNome",
                "titularCpf",
                "titularCnpj",
            )
            if row.get(key) not in (None, "")
        }
        if row.get("_geometry") is not None:
            attributes["geometry"] = row["_geometry"]

        registry_number = str(
            row.get("registroMatricula")
            or row.get("registro_matricula")
            or row.get("matricula")
            or row.get("numero_matricula")
            or ""
        ).strip() or None

        return PropertyRecord(
            property_id=code,
            registry_number=registry_number,
            address=row.get("endereco") or row.get("localizacao") or row.get("address"),
            city=row.get("municipio") or row.get("city"),
            state=row.get("uf") or row.get("state"),
            area_m2=area_m2,
            latitude=float(row["latitude"]) if row.get("latitude") not in (None, "") else None,
            longitude=float(row["longitude"]) if row.get("longitude") not in (None, "") else None,
            owner_name=row.get("titularNome") or row.get("titular_nome") or row.get("detentorNome"),
            owner_document=(
                row.get("titularCpf")
                or row.get("titularCnpj")
                or row.get("detentorCpf")
                or row.get("detentorCnpj")
            ),
            attributes=attributes,
            provenance=(Provenance(source_id="sigef", confidence=0.95),),
        )
