from __future__ import annotations

import csv
import json
import os

import httpx
from pathlib import Path
from typing import Any

from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus

from .base import SourceAdapter


SICAR_API_BASE_ENV = "IMOBHUNTER_SICAR_API_BASE_URL"
SICAR_API_TOKEN_ENV = "IMOBHUNTER_SICAR_API_TOKEN"
SICAR_API_TIMEOUT_SECONDS = 20.0


class SICARAdapter(SourceAdapter):
    """Reads authorized SICAR/CAR data for environmental enrichment.

    The official SICAR APIs are exposed through Conecta gov.br and require
    consumer onboarding/credentials. This adapter accepts an authorized local
    export/cache until runtime credentials are configured.
    """

    source_id = "sicar"
    name = "SICAR / CAR"
    category = "environmental"

    def __init__(self, data_path: str | Path | None = None) -> None:
        configured = data_path or os.getenv("IMOBHUNTER_SICAR_PATH")
        self.data_path = Path(configured) if configured else None
        self.api_base_url = os.getenv(SICAR_API_BASE_ENV, "").strip().rstrip("/")
        self.api_token = os.getenv(SICAR_API_TOKEN_ENV, "").strip()

    def status(self) -> SourceStatus:
        if self.api_base_url and self.api_token:
            return SourceStatus(self.source_id, self.name, "available", "SICAR Conecta API configured.")
        if not self.data_path:
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                "SICAR requires authorized Conecta access or a local export/cache.",
            )
        if not self.data_path.exists():
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                f"SICAR data file not found: {self.data_path}",
            )
        return SourceStatus(self.source_id, self.name, "configured")

    def _search_remote(self, code: str) -> list[PropertyRecord]:
        url = f"{self.api_base_url}/{code}"
        try:
            response = httpx.get(
                url,
                headers={"Authorization": f"Bearer {self.api_token}", "Accept": "application/json"},
                timeout=SICAR_API_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"SICAR API request failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise TypeError("SICAR API returned an invalid payload")
        return [self._to_record(payload)]

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        if request.car_code and self.api_base_url and self.api_token:
            return self._search_remote(request.car_code)
        rows = self._load()
        address = " ".join(
            part for part in (request.address, request.number) if part
        ).casefold()
        city = (request.city or "").casefold()
        state = (request.state or "").casefold()

        records: list[PropertyRecord] = []
        for row in rows:
            location = str(
                row.get("endereco")
                or row.get("enderecoImovel")
                or row.get("localizacao")
                or row.get("address")
                or ""
            )
            row_city = str(
                row.get("municipio") or row.get("municipioImovel") or row.get("city") or ""
            ).casefold()
            row_state = str(
                row.get("uf") or row.get("estado") or row.get("state") or ""
            ).casefold()

            if address and address not in location.casefold():
                continue
            if city and row_city and row_city != city:
                continue
            if state and row_state and row_state != state:
                continue

            records.append(self._to_record(row))
        return records

    def _load(self) -> list[dict[str, Any]]:
        if not self.data_path:
            return []
        if not self.data_path.exists():
            raise RuntimeError(f"SICAR data file not found: {self.data_path}")

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
                    raise ValueError("SICAR GeoJSON features must be a list")
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

            rows = payload.get("imoveis", payload) if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                raise ValueError("SICAR JSON must contain a list of rural properties")
            return rows

        raise ValueError("SICAR data must be CSV, JSON or GeoJSON")

    @staticmethod
    def _to_record(row: dict[str, Any]) -> PropertyRecord:
        area = row.get("areaTotalImovel") or row.get("area_total") or row.get("areaTotal")
        area_m2 = float(area) * 10000 if area not in (None, "") else None
        code = str(
            row.get("codigoImovel") or row.get("codigo_car") or row.get("codigoCAR") or ""
        ) or None
        location = (
            row.get("endereco")
            or row.get("enderecoImovel")
            or row.get("localizacao")
            or row.get("address")
        )

        attribute_keys = (
            "identificadorImovel",
            "codigoVersao",
            "tipoOrigem",
            "protocolo",
            "dataUltimoProtocolo",
            "statusImovel",
            "tipoImovel",
            "situacaoImovel",
            "descricaoEtapaCadastro",
            "quantidadeModulosFiscais",
            "dataCadastro",
            "dataUltimaAtualizacaoCadastro",
            "codigoMunicipio",
            "pra",
            "adesaoPRA",
            "sobreposicoesUnidadeConservacao",
            "sobreposicoesAreasEmbargadas",
            "poligonoAreaImovel",
        )
        attributes = {
            key: row.get(key)
            for key in attribute_keys
            if row.get(key) not in (None, "")
        }
        if row.get("_geometry") is not None:
            attributes["geometry"] = row["_geometry"]

        return PropertyRecord(
            property_id=code,
            address=location,
            city=row.get("municipio") or row.get("municipioImovel") or row.get("city"),
            state=row.get("uf") or row.get("estado") or row.get("state"),
            area_m2=area_m2,
            owner_name=row.get("nomeTitular") or row.get("nome_titular") or row.get("titular"),
            owner_document=row.get("cpfCnpj") or row.get("cpf_cnpj") or row.get("documentoTitular"),
            attributes=attributes,
            provenance=(Provenance(source_id="sicar", confidence=0.95),),
        )
