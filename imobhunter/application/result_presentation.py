"""Pure data-to-display helpers for the property dossier interface.

No Qt dependency: identity, field labels and copyable summaries can be tested
without building or launching a desktop installer.
"""
from __future__ import annotations

from .intelligence import PropertyDossier
from .search import SearchResult

FIELD_LABELS = {
    "address": "Endereço",
    "registry_number": "Matrícula (quando fornecida)",
    "cib": "Código CIB",
    "property_id": "Identificador cadastral da fonte",
    "owner_name": "Titular informado pela fonte",
    "owner_document": "Documento informado pela fonte",
    "block": "Quadra fiscal",
    "lot": "Lote fiscal",
    "area_m2": "Área do terreno (m²)",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "attribute:sql": "SQL / inscrição IPTU",
    "attribute:iptu_registration_number": "SQL / inscrição IPTU",
    "attribute:iptu_contributor": "Contribuinte IPTU",
    "attribute:taxpayer_name": "Contribuinte IPTU",
    "attribute:iptu_reference_year": "Ano de referência IPTU",
    "attribute:iptu_data_scope": "Período da base IPTU",
    "attribute:built_area_m2": "Área construída (m²)",
    "attribute:door_number": "Número predial",
    "attribute:sector": "Setor fiscal",
    "attribute:house_number_match": "Correspondência com o endereço",
    "attribute:cadastre_match": "Tipo de correspondência cadastral",
    "attribute:parcel_relation": "Relação com o imóvel pesquisado",
    "attribute:geometry_geojson": "Geometria do lote",
}

SOURCE_STATUSES = {
    "ok": "Respondeu com dados",
    "no_results": "Respondeu sem resultados",
    "not_configured": "Não configurada",
    "timeout": "Tempo limite excedido",
    "error": "Erro ao consultar",
}

SUMMARY_FIELDS = (
    ("Endereço", ("address",)),
    ("SQL / IPTU", ("attribute:iptu_registration_number", "attribute:sql")),
    ("Quadra", ("block",)),
    ("Lote", ("lot",)),
    ("Área do terreno (m²)", ("area_m2",)),
    ("Área construída (m²)", ("attribute:built_area_m2",)),
    ("Número predial", ("attribute:door_number",)),
    ("CIB", ("cib",)),
    ("Matrícula", ("registry_number",)),
    ("Identificador da fonte", ("property_id",)),
)


def field_label(key: str) -> str:
    if key in FIELD_LABELS:
        return FIELD_LABELS[key]
    if key.startswith("source_attribute:"):
        _, source_id, field = key.split(":", 2)
        return f"Campo oficial {source_id}: {field.replace('_', ' ')}"
    return key.removeprefix("attribute:").replace("_", " ").capitalize()


def source_status_label(status: str) -> str:
    return SOURCE_STATUSES.get(status, status)


def _facts(dossier: PropertyDossier) -> dict[str, str]:
    return {
        fact.field: str(fact.value)
        for fact in dossier.facts
        if fact.value not in (None, "")
    }


def summary_items(dossier: PropertyDossier) -> tuple[tuple[str, str], ...]:
    """Show high-value cadastral data first, with duplicate SQL fields collapsed."""
    facts = _facts(dossier)
    rows = []
    for label, candidates in SUMMARY_FIELDS:
        value = next((facts[key] for key in candidates if key in facts), None)
        if value:
            rows.append((label, value))
    return tuple(rows)


def dossier_caption(dossier: PropertyDossier) -> str:
    """Do not describe neighbors or approximate matches as confirmed parcels."""
    fields = _facts(dossier)
    match = fields.get("attribute:house_number_match", "")
    cadastral_match = fields.get("attribute:cadastre_match", "")
    relation = fields.get("attribute:parcel_relation", "")
    if match == "neighboring_parcel" or relation == "neighbor_candidate":
        return "Lote vizinho — não confirmado para o endereço"
    if match == "exact":
        return "Número predial confirmado pela fonte"
    if match == "geocoded_spatial_match":
        return "Lote encontrado por geocodificação — conferir número"
    if match == "geocoded_spatial_candidate" or cadastral_match == "spatial_candidate_only":
        return "Lote cadastral candidato — correspondência não confirmada"
    if fields.get("attribute:record_kind") == "geocoded_address_only":
        return "Endereço geocodificado — sem confirmação cadastral"
    return "Dados recebidos — confira a identificação cadastral"


def summary_text(result: SearchResult) -> str:
    """Copy a human-readable, source-aware summary to the system clipboard."""
    lines = ["ImobHunter-BR — Resumo da pesquisa"]
    lines.append(f"Endereço pesquisado: {result.normalized.normalized}")
    for index, dossier in enumerate(result.dossiers, 1):
        lines.extend(("", f"Imóvel {index}: {dossier_caption(dossier)}"))
        lines.extend(f"{name}: {value}" for name, value in summary_items(dossier))
        sources = sorted({fact.provenance.source_id for fact in dossier.facts})
        lines.append("Fontes dos dados: " + (", ".join(sources) or "não informadas"))
    if not result.dossiers:
        lines.extend(("", "Nenhum dossiê cadastral consolidado."))
    lines.append("")
    lines.append("Situação das fontes:")
    for source in result.sources:
        lines.append(
            f"{source.name}: {source_status_label(source.status)} "
            f"({source.records_count} registro(s))"
        )
    return "\n".join(lines)
