from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from imobhunter.application.address_geocoding import CachedAddressGeocoder
from imobhunter.domain.models import SearchRequest
from imobhunter.sources.geosampa import GeoSampaAdapter
from imobhunter.sources.official_municipal_services import OfficialMunicipalServicesAdapter

CASES = (
    ("São Paulo", "SP", "Avenida Paulista", "1000", "geosampa"),
    ("Praia Grande", "SP", "Avenida Presidente Costa e Silva", "100", "official"),
    ("Belo Horizonte", "MG", "Rua da Bahia", "1000", "official"),
    ("Rio de Janeiro", "RJ", "Avenida Rio Branco", "1", "official"),
)


def main() -> int:
    results = []
    failed = False
    with tempfile.TemporaryDirectory(prefix="imobhunter-live-cadastre-") as temp:
        root = Path(temp)
        geocoder = CachedAddressGeocoder(
            root / "geocoding.sqlite3",
            "ImobHunter-BR/0.1.19 (live municipal integration test)",
        )
        geosampa = GeoSampaAdapter(geocoder=geocoder)
        official = OfficialMunicipalServicesAdapter(
            cache_dir=root / "cache", geocoder=geocoder
        )
        for city, state, street, number, source in CASES:
            adapter = geosampa if source == "geosampa" else official
            request = SearchRequest(
                address=street, number=number, city=city, state=state
            )
            records = adapter.search(request)
            record_rows = [{
                "address": record.address,
                "quadra": record.block,
                "lote": record.lot,
                "area_m2": record.area_m2,
                "built_area_m2": record.attributes.get("built_area_m2"),
                "sql": record.attributes.get("sql"),
                "sql_status": record.attributes.get("sql_status"),
                "cadastre_match": (
                    record.attributes.get("cadastre_match")
                    or record.attributes.get("house_number_match")
                    or "not_marked_by_adapter"
                ),
                "geometry": bool(record.attributes.get("geometry_geojson")),
                "service_url": record.attributes.get("service_url"),
                "layer": record.attributes.get("wfs_layer"),
            } for record in records[:5]]
            error = getattr(adapter, "last_errors", {}).get(city)
            diagnostics = getattr(adapter, "last_diagnostics", {}).get(city)
            if source == "geosampa" and records:
                diagnostics = {
                    "endpoint": getattr(adapter, "endpoint", None),
                    "layer": getattr(adapter, "layer", None),
                    "source": "GeoSampaAdapter",
                }
            row = {
                "municipality": f"{city}/{state}",
                "address_tested": f"{street}, {number}",
                "adapter": adapter.source_id,
                "records_returned": len(records),
                "sample_records": record_rows,
                "adapter_error": error,
                "diagnostics": diagnostics,
                "result": "PASS_FEATURES_RETURNED" if records else "FAIL_NO_FEATURES",
            }
            results.append(row)
            if not records:
                failed = True

    print(json.dumps(results, ensure_ascii=False, indent=2))
    if failed:
        print(
            "LIVE MUNICIPAL TEST FAILED: one or more real-address searches returned "
            "no cadastral features. Inspect the per-source error or layer response above.",
            file=sys.stderr,
        )
        return 1
    print(
        "LIVE MUNICIPAL TEST PASSED: every test returned one or more official "
        "cadastral features. Spatial candidates are not proof of an exact address "
        "match or legal ownership; inspect cadastre_match and source fields."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
