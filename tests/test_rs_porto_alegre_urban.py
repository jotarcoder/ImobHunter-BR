"""The Porto Alegre SMF key must not be joined to DMWEB urban tables."""
import httpx

from imobhunter.domain.models import PropertyRecord
from imobhunter.sources.rs_porto_alegre_urban import BASE, enrich_dmweb_lots


def test_dmweb_join_by_exact_id_only_without_tax_sql():
    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        params = request.url.params
        assert params["where"] == "id_lotes IN (17)"
        assert params["returnGeometry"] == "false"
        assert len(params["outFields"]) < 150
        assert request.url.path.endswith(("/3/query", "/4/query", "/5/query"))
        layer = int(request.url.path.split("/")[-2])
        tables = {
            3: [{"id_lotes": 17, "sub_indice": "3", "bairro": "CENTRO"}],
            4: [{"id_lotes": 17, "parcel_area": 125.5, "zone_percent": "Z1 100%"}],
            5: [{"id_lotes": 17, "json_front": "FRONTAGE"}],
        }
        return httpx.Response(200, json={"features": [{"attributes": item} for item in tables[layer]]})

    lot = PropertyRecord(city="Porto Alegre", state="RS", attributes={
        "service_url": BASE + "/0", "parcel_identifier": "17",
        "sql": None, "iptu_registration_number": None,
    })
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        records, diagnostic = enrich_dmweb_lots([lot], client.get)
    assert len(calls) == 3
    assert records[0].area_m2 == 125.5
    assert records[0].attributes["urban_planning_dmweb"]["sub_indice"] == "3"
    assert records[0].attributes["zoning_dmweb"]["zone_percent"] == "Z1 100%"
    assert records[0].attributes["frontage_dmweb_available"] is True
    assert diagnostic["table_5_matches"] == 1
    assert records[0].attributes["sql"] is None


def test_smf_numbloCO_is_not_related_dmweb_id():
    calls = []
    smf = PropertyRecord(city="Porto Alegre", state="RS", attributes={
        "service_url": "https://gis-smamus.portoalegre.rs.gov.br/server/rest/services/POA___Consultas_MIL1/MapServer/98",
        "parcel_identifier": "0000123456", "fiscal_lot_identifier": "0000123456",
    })
    result, diagnostic = enrich_dmweb_lots([smf], lambda *_args: calls.append(True))
    assert result == [smf] and calls == []
    assert diagnostic["requested_parcel_ids"] == 0


def test_optional_table_unavailable_cannot_erase_parcel():
    def fail(*_args):
        raise httpx.ConnectError("temporarily unavailable")
    rec = PropertyRecord(city="Porto Alegre", state="RS", attributes={
        "service_url": BASE + "/0", "parcel_identifier": "27",
    })
    records, diagnostic = enrich_dmweb_lots([rec], fail)
    assert records == [rec]
    assert all(diagnostic[f"table_{layer}_unavailable"] == "ConnectError" for layer in (3, 4, 5))


def test_malicious_or_invalid_id_cannot_build_sql_predicate():
    calls = []
    rec = PropertyRecord(attributes={
        "service_url": BASE + "/0", "parcel_identifier": "17 OR 1=1",
    })
    rows, _ = enrich_dmweb_lots([rec], lambda *_args: calls.append(True))
    assert rows == [rec] and not calls
