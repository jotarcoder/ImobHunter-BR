from __future__ import annotations

import csv
import json
from pathlib import Path

from imobhunter.application.export import export_search_result_csv, export_search_result_json
from imobhunter.application.search import SearchResult, SourceSearchResult
from imobhunter.application.address import normalize_request
from imobhunter.application.intelligence import build_dossier
from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest


def sample_result() -> SearchResult:
    record = PropertyRecord(
        property_id="P-123",
        address="R PAMPLONA",
        city="SAO PAULO",
        state="SP",
        block="020",
        lot="0030",
        area_m2=420.5,
        attributes={"geometry_geojson": "{\"type\":\"Point\",\"coordinates\":[-46.65,-23.57]}", "source": "geosampa"},
        provenance=(Provenance("geosampa", confidence=0.95),),
    )
    records = (record,)
    return SearchResult(
        normalized=normalize_request(SearchRequest(address="Rua Pamplona", number="1578")),
        records=records,
        dossiers=(build_dossier("P-123", records),),
        sources=(SourceSearchResult("geosampa", "GeoSampa", "ok", 1),),
    )


def test_json_export_preserves_records_sources_and_dossier(tmp_path: Path) -> None:
    target = tmp_path / "dossier.json"
    export_search_result_json(sample_result(), target)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["records"][0]["property_id"] == "P-123"
    assert payload["records"][0]["attributes"]["source"] == "geosampa"
    assert payload["dossiers"][0]["identity"] == "P-123"
    assert payload["sources"][0]["status"] == "ok"


def test_csv_export_contains_facts_and_provenance(tmp_path: Path) -> None:
    target = tmp_path / "dossier.csv"
    export_search_result_csv(sample_result(), target)

    with target.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows
    address = next(row for row in rows if row["field"] == "address")
    assert address["value"] == "R PAMPLONA"
    assert address["source_id"] == "geosampa"
    assert float(address["source_confidence"]) == 0.95
