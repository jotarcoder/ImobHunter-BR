"""Mogi das Cruzes: official CKAN metadata and licensed historical CSV projection.

The public catalogue contains 2016-2024 records, not a live municipal
address-to-IPTU API. No raw taxpayer, debt, monetary or owner data leaves
the locally imported file. Do not claim cadastro_id is current SQL.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
import re
from typing import Any

from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest
from imobhunter.sources.sc_municipal_cadastre import (
    _float, _number, _number_matches, _street_tokens,
)

MOGI_DATASET_API = "https://dados.mogidascruzes.sp.gov.br/api/3/action/package_show"
MOGI_DATASET_PAGE = (
    "https://dados.mogidascruzes.sp.gov.br/pt_BR/dataset/cadastro-imobiliario"
)
MOGI_DATASET_ID = "cadastro-imobiliario"
MOGI_LAST_PUBLISHED_EXERCISE = 2024
Fetch = Callable[[str, dict[str, Any]], Any]


def mogi_catalogue(
    _request: SearchRequest, fetch: Fetch, _source_id: str,
) -> tuple[list[PropertyRecord], dict[str, Any]]:
    """Only CKAN metadata; do not download or publish cadastral/taxpayer rows."""
    response = fetch(MOGI_DATASET_API, {"id": MOGI_DATASET_ID})
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("CKAN não confirmou metadados públicos do cadastro.")
    package = payload.get("result")
    if not isinstance(package, dict) or not isinstance(package.get("resources"), list):
        raise TypeError("Metadados CKAN sem lista de recursos.")
    sources = [
        entry for entry in package["resources"] if isinstance(entry, dict)
        and str(entry.get("name") or "").startswith("pmmc_imobiliario_")
        and str(entry.get("name") or "").lower().endswith(".csv")
    ]
    observed_years = sorted({
        int(match.group(1))
        for entry in sources
        for match in [re.search(r"pmmc_imobiliario_(20[0-2][0-9])_", str(entry.get("name")))]
        if match is not None
    })
    diag: dict[str, Any] = {
        "result": "historical_dataset_only",
        "dataset_url": MOGI_DATASET_PAGE,
        "metadata_api": MOGI_DATASET_API,
        "source_id": MOGI_DATASET_ID,
        "dataset_license": package.get("license_id") or "not_specified",
        "last_published_exercise": observed_years[-1] if observed_years else None,
        "published_exercises": observed_years,
        "available_cadastre_files": len(sources),
        "registration_verified": False,
        "sql_status": "not_verified",
        "quadra_lote_status": "not_published_as_explicit_columns",
        "remote_address_search": "not_available",
        "commercial_reuse": "requires_dataset_specific_license_confirmation",
        "manual_import": "existing_user_authorized_file_support",
        "automated_download": False,
    }
    return [], diag


def mogi_historical_file_record(
    row: Mapping[str, Any],
    request: SearchRequest,
    source_id: str,
    local_file: str,
) -> PropertyRecord | None:
    """Filter authorized local 2024 CKAN export by *exact* street and door.

    Never return owner names, financial rows, unverified SQL, or a neighboring
    building. The cadastral ID is only a dated historic reference, not the
    individual present-day tax registration.
    """
    if not request.address or not _number(request.number):
        return None
    official_street = row.get("logradouro")
    official_number = row.get("nro_local")
    wanted, available = _street_tokens(request.address), _street_tokens(official_street)
    if not wanted or wanted != available:
        return None
    if not _number_matches(str(request.number), official_number):
        return None
    cadastre_id = row.get("cadastro_id")
    if cadastre_id is None or not str(cadastre_id).strip():
        return None
    cid = str(cadastre_id).strip()
    if len(cid) > 64:
        return None
    area = _float(row.get("area_terreno"))
    year_keys = [
        match.group(1)
        for column in row
        for match in [re.fullmatch(r"situacao\((20[0-2][0-9])\)", str(column).casefold())]
        if match is not None
    ]
    source_year = int(year_keys[0]) if len(year_keys) == 1 else None
    sanitized = {
        "historical_cadastro_id": cid,
        "source": source_id,
        "official_source": "Prefeitura de Mogi das Cruzes — Cadastro Imobiliário histórico",
        "official_dataset_page": MOGI_DATASET_PAGE,
        "imported_municipal_file": local_file,
        "source_year": source_year,
        "source_year_status": "column_verified" if source_year else "unknown",
        "historical_data": True,
        "source_properties": {
            "cadastro_id": cid, "logradouro": str(official_street),
            "nro_local": _number(official_number),
            "area_terreno": area,
        },
        "municipal_registration_number": None,
        "iptu_registration_number": None,
        "sql": None,
        "sql_status": "not_validated_from_historical_dataset",
        "quadra_lote_status": "not_provided_by_dataset",
        "cadastre_match": "exact_historical_address_only",
        "owner_status": "not_requested",
        "geometry_geojson": None,
    }
    return PropertyRecord(
        address=f"{official_street}, {_number(official_number)}",
        city="Mogi das Cruzes", state="SP",
        area_m2=area, block=None, lot=None,
        attributes=sanitized,
        provenance=(
            Provenance(
                source_id=source_id,
                confidence=0.60,
                reference=f"Cadastro Imobiliário {source_year or 'ano não identificado'}: {local_file}",
            ),
        ),
    )
