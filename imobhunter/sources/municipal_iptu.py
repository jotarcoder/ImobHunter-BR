from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus, TaxDebt

from .base import SourceAdapter


class MunicipalIPTUAdapter(SourceAdapter):
    """Local municipal IPTU/debt adapter.

    Municipal tax systems differ by city. This adapter consumes an authorized
    municipal export/cache and preserves the query state instead of treating
    an unavailable or authentication-protected portal as "no debt".
    """

    source_id = "municipal_iptu"
    name = "IPTU municipal"
    category = "municipal_tax"

    def __init__(self, data_path: str | Path | None = None) -> None:
        configured = data_path or os.getenv("IMOBHUNTER_IPTU_PATH")
        self.data_path = Path(configured) if configured else None

    def status(self) -> SourceStatus:
        if not self.data_path:
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                "Configure an authorized municipal IPTU export/cache.",
            )
        if not self.data_path.exists():
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                f"IPTU data file not found: {self.data_path}",
            )
        return SourceStatus(self.source_id, self.name, "configured")

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        rows = self._load()
        matches = [row for row in rows if self._matches(row, request)]
        return [self._to_record(row) for row in matches]

    def _load(self) -> list[dict[str, Any]]:
        if not self.data_path:
            return []
        if not self.data_path.exists():
            raise RuntimeError(f"IPTU data file not found: {self.data_path}")
        if self.data_path.suffix.lower() == ".csv":
            with self.data_path.open("r", encoding="utf-8-sig", newline="") as handle:
                return list(csv.DictReader(handle))
        payload = json.loads(self.data_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = payload.get("data", payload.get("items", payload))
        if not isinstance(payload, list):
            raise ValueError("IPTU JSON must contain a list or data/items list")
        return payload

    @staticmethod
    def _matches(row: dict[str, Any], request: SearchRequest) -> bool:
        def norm(value: Any) -> str:
            return " ".join(str(value or "").upper().split())

        if request.city and norm(row.get("municipio") or row.get("city")) != norm(request.city):
            return False
        if request.state and norm(row.get("uf") or row.get("state")) != norm(request.state):
            return False

        sql = norm(row.get("sql") or row.get("numero_contribuinte") or row.get("cadastro"))
        requested_id = norm(request.block) if request.block and request.lot else ""
        if requested_id and sql and requested_id == sql:
            return True

        address = norm(row.get("endereco") or row.get("address") or row.get("logradouro"))
        number = norm(row.get("numero") or row.get("addr:housenumber"))
        query = norm(" ".join(part for part in (request.address, request.number) if part))
        row_query = norm(" ".join(part for part in (address, number) if part))
        return bool(query and row_query and query == row_query)

    @classmethod
    def _to_record(cls, row: dict[str, Any]) -> PropertyRecord:
        debts: list[TaxDebt] = []
        raw_debts = row.get("tax_debts") or row.get("debitos") or []
        if isinstance(raw_debts, str):
            raw_debts = json.loads(raw_debts) if raw_debts.strip().startswith("[") else []
        if isinstance(raw_debts, list):
            for item in raw_debts:
                if not isinstance(item, dict):
                    continue
                debts.append(
                    TaxDebt(
                        status=str(item.get("status") or "unknown"),
                        year=cls._int(item.get("year") or item.get("ano") or item.get("exercicio")),
                        amount=cls._float(item.get("amount") or item.get("valor")),
                        due_date=item.get("due_date") or item.get("vencimento"),
                        description=item.get("description") or item.get("descricao"),
                    )
                )

        query_status = str(row.get("query_status") or row.get("status_consulta") or "no_debt_found")
        attributes = {
            "iptu_query_status": query_status,
            "iptu_query_date": row.get("query_date") or row.get("data_consulta"),
            "iptu_official_source": row.get("official_source") or row.get("fonte_oficial"),
            "iptu_authentication_required": cls._bool(row.get("authentication_required")),
            "iptu_captcha_required": cls._bool(row.get("captcha_required")),
        }
        return PropertyRecord(
            property_id=str(row.get("property_id") or row.get("sql") or row.get("numero_contribuinte") or "") or None,
            cib=row.get("cib"),
            address=row.get("endereco") or row.get("address"),
            city=row.get("municipio") or row.get("city"),
            state=row.get("uf") or row.get("state"),
            block=row.get("quadra") or row.get("block"),
            lot=row.get("lote") or row.get("lot"),
            owner_name=row.get("owner_name") or row.get("contribuinte"),
            owner_document=row.get("owner_document"),
            attributes=attributes,
            tax_debts=tuple(debts),
            provenance=(Provenance(source_id="municipal_iptu", confidence=0.95, reference=row.get("official_source")),),
        )

    @staticmethod
    def _float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        return float(value)

    @staticmethod
    def _int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        return int(value)

    @staticmethod
    def _bool(value: Any) -> bool:
        return str(value).strip().lower() in {"1", "true", "yes", "sim"}
