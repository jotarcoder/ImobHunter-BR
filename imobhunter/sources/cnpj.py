from __future__ import annotations

import csv
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus

from .base import SourceAdapter


class CNPJAdapter(SourceAdapter):
    """Reads authorized/open CNPJ establishment data for company enrichment.

    The official CNPJ API is available through Conecta gov.br with
    authentication. Receita Federal also publishes CNPJ open-data files.
    This adapter consumes an authorized local export/cache so heavy datasets
    remain on the user's machine.
    """

    source_id = "cnpj"
    name = "Receita Federal / CNPJ"
    category = "company"

    def __init__(self, data_path: str | Path | None = None) -> None:
        configured = data_path or os.getenv("IMOBHUNTER_CNPJ_PATH")
        self.data_path = Path(configured) if configured else None

    def status(self) -> SourceStatus:
        if not self.data_path:
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                "CNPJ requires an authorized API integration or a local/open-data export.",
            )
        if not self.data_path.exists():
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                f"CNPJ data file not found: {self.data_path}",
            )
        return SourceStatus(self.source_id, self.name, "configured")

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        rows = self._load()
        address = self._normalize_text(
            " ".join(part for part in (request.address, request.number) if part)
        )
        city = self._normalize_text(request.city or "")
        state = self._normalize_text(request.state or "")

        records: list[PropertyRecord] = []
        for row in rows:
            row_address = self._normalize_text(
                " ".join(
                    str(row.get(key) or "")
                    for key in ("logradouro", "tipo_logradouro", "numero", "complemento")
                )
            )
            row_city = self._normalize_text(
                str(row.get("municipio") or row.get("city") or "")
            )
            row_state = self._normalize_text(
                str(row.get("uf") or row.get("state") or "")
            )

            if address and address not in row_address:
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
            raise RuntimeError(f"CNPJ data file not found: {self.data_path}")

        suffix = self.data_path.suffix.lower()
        if suffix == ".csv":
            with self.data_path.open("r", encoding="utf-8-sig", newline="") as handle:
                return list(csv.DictReader(handle))

        if suffix == ".json":
            payload = json.loads(self.data_path.read_text(encoding="utf-8"))
            rows = payload.get("estabelecimentos", payload) if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                raise ValueError("CNPJ JSON must contain a list of establishments")
            return rows

        raise ValueError("CNPJ data must be CSV or JSON")

    @staticmethod
    def _normalize_text(value: str) -> str:
        text = unicodedata.normalize("NFKD", value)
        text = "".join(char for char in text if not unicodedata.combining(char))
        return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", text.upper())).strip()

    @staticmethod
    def _to_record(row: dict[str, Any]) -> PropertyRecord:
        cnpj = str(
            row.get("cnpj")
            or row.get("CNPJ")
            or row.get("cnpj_basico")
            or row.get("cnpj_completo")
            or ""
        ).strip() or None
        company_name = (
            row.get("razao_social")
            or row.get("razaoSocial")
            or row.get("nome_empresarial")
            or row.get("nomeEmpresarial")
        )
        area = row.get("area_m2") or row.get("area")
        area_m2 = float(area) if area not in (None, "") else None

        attributes = {
            key: row.get(key)
            for key in (
                "nome_fantasia",
                "nomeFantasia",
                "situacao_cadastral",
                "situacaoCadastral",
                "data_situacao_cadastral",
                "dataSituacaoCadastral",
                "motivo_situacao_cadastral",
                "motivoSituacaoCadastral",
                "natureza_juridica",
                "naturezaJuridica",
                "data_abertura",
                "dataAbertura",
                "porte",
                "opcao_simples",
                "opcaoSimples",
                "opcao_mei",
                "opcaoMei",
                "situacao_especial",
                "situacaoEspecial",
                "data_situacao_especial",
                "dataSituacaoEspecial",
                "cnae_principal",
                "cnaePrincipal",
                "capital_social",
                "capitalSocial",
                "tipo_estabelecimento",
                "tipoEstabelecimento",
            )
            if row.get(key) not in (None, "")
        }
        if company_name:
            attributes["company_name"] = company_name
        if cnpj:
            attributes["cnpj"] = cnpj

        return PropertyRecord(
            property_id=cnpj,
            address=(
                " ".join(
                    str(row.get(key) or "").strip()
                    for key in ("tipo_logradouro", "logradouro", "numero", "complemento")
                    if row.get(key) not in (None, "")
                )
                or row.get("endereco")
                or row.get("address")
            ),
            city=row.get("municipio") or row.get("city"),
            state=row.get("uf") or row.get("state"),
            area_m2=area_m2,
            owner_name=company_name,
            owner_document=cnpj,
            latitude=float(row["latitude"]) if row.get("latitude") not in (None, "") else None,
            longitude=float(row["longitude"]) if row.get("longitude") not in (None, "") else None,
            attributes=attributes,
            provenance=(Provenance(source_id="cnpj", confidence=0.95),),
        )
