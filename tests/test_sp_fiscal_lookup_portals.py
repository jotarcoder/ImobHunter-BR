"""Fiscal portals must not fabricate property registrations."""
import httpx
from imobhunter.application.municipal_endpoints import settings_endpoint_rows
from imobhunter.application.source_probe import probe_endpoint
from imobhunter.domain.models import SearchRequest
from imobhunter.sources.official_municipal_services import OfficialMunicipalServicesAdapter
from imobhunter.sources.sp_fiscal_lookup_portals import (
    CAMPINAS_LOOKUP, JUNDIAI_LOOKUP, SANTO_ANDRE_LOOKUP,
    campinas, portal_diagnostic,
)


def test_campinas_fiscal_handoff_has_no_fabricated_sql(tmp_path):
    def handler(_req):
        raise AssertionError("No undocumented API should be called")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OfficialMunicipalServicesAdapter(cache_dir=tmp_path, client=client)
    rows = adapter.search(SearchRequest(
        address="Avenida Francisco Glicerio", number="500",
        city="Campinas", state="SP",
    ))
    client.close()
    assert rows == []
    diag = adapter.last_diagnostics["Campinas"]
    assert diag["result"] == "official_browser_lookup_required"
    assert diag["portal_url"] == CAMPINAS_LOOKUP
    assert diag["registration_verified"] is False
    assert "Campinas" in adapter.last_errors


def test_invalid_number_never_becomes_address_lookup():
    for number in ("100 OR 1=1", None, "", "1 2"):
        rows, diag = campinas(SearchRequest(
            address="Rua Ferreira Penteado", number=number,
            city="Campinas", state="SP",
        ), "official")
        assert rows == []
        assert diag["result"] == "street_and_numeric_number_required"


def test_official_portal_endpoints_are_only_website_references():
    rows = {item["id"]: item for item in settings_endpoint_rows()}
    for key, url in (
        ("campinas_codigo_cartografico", CAMPINAS_LOOKUP),
        ("santo_andre_fiscal_portal", SANTO_ANDRE_LOOKUP),
        ("jundiai_fiscal_portal", JUNDIAI_LOOKUP),
    ):
        assert rows[key]["url"] == url
        assert rows[key]["kind"] == "website"
        assert rows[key]["role"] == "reference"
        assert rows[key]["state"] == "SP"


def test_portal_healthcheck_is_not_sql_query():
    def handler(_req):
        return httpx.Response(200, text="<html>Portal oficial</html>")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_endpoint({
            "id": "campinas_codigo_cartografico",
            "url": CAMPINAS_LOOKUP, "kind": "website",
        }, client=client)
    assert result.state == "responded"
    assert "não foi verificada API" in result.message


def test_santo_andre_jundiai_require_manual_confirmation():
    for city, url in (
        ("Santo André", SANTO_ANDRE_LOOKUP),
        ("Jundiaí", JUNDIAI_LOOKUP),
    ):
        d = portal_diagnostic(SearchRequest(
            address="Rua Exemplo", number="100", city=city, state="SP",
        ), url, city)
        assert d["registration_verified"] is False
        assert d["quadra_lote_status"] == "not_automated"
        assert d["automated_property_records"] == 0
        assert d["portal_url"] == url
