import json
from pathlib import Path

ALLOWED_STATUSES = {
    "implemented",
    "conditional",
    "discovery_only",
    "framework_only",
    "planned",
}


def test_source_registry_has_unique_ids_and_explicit_evidence():
    path = Path(__file__).parents[1] / "data" / "source-registry" / "sources.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    sources = payload["sources"]

    ids = [source["id"] for source in sources]
    assert ids
    assert len(ids) == len(set(ids))
    assert {"implemented", "conditional", "discovery_only", "planned"} <= set(
        payload["status_definitions"]
    )

    for source in sources:
        assert source["status"] in ALLOWED_STATUSES
        assert source.get("validation")
        assert source.get("scope")
        assert source.get("limitations")


def test_cnpj_and_discovery_sources_do_not_claim_universal_live_coverage():
    path = Path(__file__).parents[1] / "data" / "source-registry" / "sources.json"
    sources = {
        source["id"]: source
        for source in json.loads(path.read_text(encoding="utf-8"))["sources"]
    }

    assert sources["cnpj"]["status"] == "conditional"
    assert "não descobre sozinha" in sources["cnpj"]["limitations"]
    assert sources["national_municipal_cadastre"]["status"] == "discovery_only"
    assert "não comprova" in sources["national_municipal_cadastre"]["limitations"]
