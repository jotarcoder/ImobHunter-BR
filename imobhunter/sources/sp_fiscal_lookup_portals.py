"""Official address-to-fiscal lookup portals. Websites are not undocumented APIs."""
from __future__ import annotations
from imobhunter.domain.models import PropertyRecord, SearchRequest
from imobhunter.sources.sc_municipal_cadastre import _number, _street_tokens

CAMPINAS_LOOKUP = "https://zoneamento.campinas.sp.gov.br/"
CAMPINAS_INFO = "https://portal-adm.campinas.sp.gov.br/servico/busca-do-codigo-cartografico"
SANTO_ANDRE_LOOKUP = "https://sigamapa.santoandre.sp.gov.br/index.aspx?id=search_sql"
JUNDIAI_LOOKUP = "https://geo.jundiai.sp.gov.br/geojundiai/cfImob.jsp"


def portal_diagnostic(request: SearchRequest, portal_url: str, city: str) -> dict:
    ok = bool(_number(request.number) and _street_tokens(request.address))
    return {
        "result": "official_browser_lookup_required" if ok
                  else "street_and_numeric_number_required",
        "city": city, "state": "SP", "portal_url": portal_url,
        "number": _number(request.number),
        "registration_verified": False,
        "sql_status": "requires_official_address_lookup",
        "quadra_lote_status": "not_automated",
        "query_mode": "browser_portal_not_cadastral_api",
        "manual_steps": (
            "Digite logradouro e numero no portal oficial e confirme o "
            "imovel no mapa. Nao inferir SQL/IPTU de um lote proximo."
        ),
        "automated_property_records": 0,
    }


def campinas(
    request: SearchRequest, _source_id: str,
) -> tuple[list[PropertyRecord], dict]:
    return [], portal_diagnostic(request, CAMPINAS_LOOKUP, "Campinas")
