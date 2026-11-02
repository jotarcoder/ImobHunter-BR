"""The live evidence report must preserve source and geometry uncertainty."""
import json

from imobhunter.domain.models import PropertyRecord, Provenance
from scripts.live_municipal_cadastral_evidence import safe_record


def test_evidence_reports_official_polygon_and_iptu_only_when_returned():
    polygon = {
        "type": "Polygon",
        "coordinates": [[
            [-46.326, -23.935], [-46.325, -23.935],
            [-46.325, -23.934], [-46.326, -23.935],
        ]],
    }
    record = PropertyRecord(
        address="Praça Visconde de Mauá", city="Santos", state="SP",
        block="020", lot="004", area_m2=190,
        property_id="santos:feature.123",
        attributes={
            "geometry_geojson": json.dumps(polygon),
            "sql": "111.020.004",
            "house_number_match": "geocoded_spatial_candidate",
            "source_properties": {"quadra": "020", "sql": "111.020.004"},
        },
        provenance=(Provenance("official_municipal_services"),),
    )
    result = safe_record(record)
    assert result["valid_cadastral_polygon"] is True
    assert result["map_renderable"] is True
    assert result["map_classification"] == "candidate"
    assert result["sql"] == "111.020.004"
    assert result["block"] == "020"
    assert result["lot"] == "004"


def test_evidence_invalid_polygon_is_never_labeled_renderable():
    record = PropertyRecord(
        city="Bertioga", state="SP",
        property_id="arbitrary-layer-feature-id",
        attributes={
            "geometry_geojson": '{"type":"Point","coordinates":[500000,7000000]}',
        },
    )
    result = safe_record(record)
    assert result["geometry_returned"] is True
    assert result["map_renderable"] is False
    assert result["valid_cadastral_polygon"] is False
    assert result["map_classification"] is None
    assert result["sql"] is None
    assert result["iptu_registration_number"] is None
