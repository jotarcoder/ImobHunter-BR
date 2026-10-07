from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus

from .base import SourceAdapter


class SNCRAdapter(SourceAdapter):
    """Reads authorized SNCR/INCRA data for rural-property enrichment.

    The official SNCR API is exposed through Conecta gov.br and requires
    consumer onboarding/credentials. This adapter therefore accepts an
    authorized local export/cache until runtime credentials are configured.
    """

    source_id = "sncr"
    name = "INCRA / SNCR"
    category = "rural"

    def __init__(self, data_path: str | Path | None = None) -> None:
        configured = data_path or os.getenv("IMOBHUNTER_SNCR_PATH")
        self.data_path = Path(configured) if configured else None

    def status(self) -> SourceStatus:
        if not self.data_path:
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                "SNCR requires authorized Conecta access or a local export/cache.",
            )
        if not self.data_path.exists():
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                f"SNCR data file not found: {self.data_path}",
            )
        return SourceStatus(self.source_id, self.name, "configured")

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        rows = self._load()
        address = " ".join(
            part for part in (request.address, request.number) if part
        ).casefold()
        city = (request.city or "").casefold()
        state = (request.state or "").casefold()

        records: list[PropertyRecord] = []
        for row in rows:
            location = str(
                row.get("localizacao_imovel_rural")
                or row.get("localizacaoImovelRural")
                or row.get("localizacao")
                or row.get("address")
                or ""
            )
            row_city = str(row.get("city") or row.get("municipio") or "").casefold()
            row_state = str(row.get("state") or row.get("uf") or "").casefold()

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
            raise RuntimeError(f"SNCR data file not found: {self.data_path}")

        if self.data_path.suffix.lower() == ".csv":
            with self.data_path.open("r", encoding="utf-8-sig", newline="") as handle:
                return list(csv.DictReader(handle))

        if self.data_path.suffix.lower() == ".json":
            payload = json.loads(self.data_path.read_text(encoding="utf-8"))
            rows = payload.get("imoveis", payload) if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                raise ValueError("SNCR JSON must contain a list of rural properties")
            return rows

        raise ValueError("SNCR data must be CSV or JSON")

    @staticmethod
    def _to_record(row: dict[str, Any]) -> PropertyRecord:
        area = row.get("area_total") or row.get("areaTotal")
        area_m2 = float(area) * 10000 if area not in (None, "") else None
        code = str(row.get("codigo_imovel") or row.get("codigoImovel") or "") or None
        location = (
            row.get("localizacao_imovel_rural")
            or row.get("localizacaoImovelRural")
            or row.get("localizacao")
            or row.get("address")
        )

        attributes = {
            key: row.get(key)
            for key in (
                "nome_imovel_rural",
                "nomeImovelRural",
                "situacao_imovel",
                "situacaoImovel",
                "motivo_cancelamento",
                "motivoCancelamento",
                "data_cancelamento",
                "dataCancelamento",
                "qtd_area_modulos_fiscais",
                "qtdAraeModulosFiscais",
                "inibicao",
                "data_inibicao",
                "dataInibicao",
                "codigo_certificacao_snci",
                "codigoCertificacaoSnci",
                "data_ultima_atualizacao_cadastral",
                "dataUltimaAtualizacaoCadastral",
            )
            if row.get(key) not in (None, "")
        }

        return PropertyRecord(
            property_id=code,
            address=location,
            city=row.get("city") or row.get("municipio"),
            state=row.get("state") or row.get("uf"),
            area_m2=area_m2,
            owner_name=row.get("nome_titular") or row.get("nomeTitular") or row.get("titular"),
            owner_document=row.get("cpf_cnpj") or row.get("cpfCnpj") or row.get("documento_titular"),
            attributes=attributes,
            provenance=(Provenance(source_id="sncr", confidence=0.95),),
        )
