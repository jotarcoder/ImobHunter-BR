from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
FIELD_MAP = {
    "quadra": lambda record: record.block,
    "lote": lambda record: record.lot,
    "area_m2": lambda record: record.area_m2,
    "sql_iptu": lambda record: record.attributes.get("sql"),
    "cib": lambda record: record.cib,
    "matricula": lambda record: record.attributes.get("matricula"),
    "geometry": lambda record: record.attributes.get("geometry_geojson"),
}


def _record_summary(record: Any) -> dict[str, Any]:
    available = [
        name for name, getter in FIELD_MAP.items()
        if getter(record) not in (None, "", False)
    ]
    return {
        "address": record.address,
        "quadra": record.block,
        "lote": record.lot,
        "area_m2": record.area_m2,
        "sql": record.attributes.get("sql"),
        "sql_status": record.attributes.get("sql_status"),
        "cib": record.cib,
        "matricula": record.attributes.get("matricula"),
        "cadastre_match": (
            record.attributes.get("cadastre_match")
            or record.attributes.get("house_number_match")
            or "not_marked_by_adapter"
        ),
        "geometry": bool(record.attributes.get("geometry_geojson")),
        "service_url": record.attributes.get("service_url"),
        "layer": record.attributes.get("wfs_layer"),
        "fields_available": available,
    }


def build_report() -> dict[str, Any]:
    tested_at = datetime.now(timezone.utc).isoformat()
    results = []
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
            error = getattr(adapter, "last_errors", {}).get(city)
            diagnostics = getattr(adapter, "last_diagnostics", {}).get(city)
            if source == "geosampa" and records:
                diagnostics = {
                    "endpoint": getattr(adapter, "endpoint", None),
                    "layer": getattr(adapter, "layer", None),
                    "source": "GeoSampaAdapter",
                }
            summaries = [_record_summary(record) for record in records[:5]]
            has_geometry = any(row["geometry"] for row in summaries)
            if error:
                coverage_status = "query_failed"
                connection_status = "error"
            elif has_geometry:
                coverage_status = "parcel_found"
                connection_status = "responded"
            elif records:
                coverage_status = "address_found"
                connection_status = "responded"
            elif diagnostics:
                coverage_status = "connection_ok"
                connection_status = "responded"
            else:
                coverage_status = "no_result"
                connection_status = "unknown"
            fields = sorted({
                field for row in summaries for field in row["fields_available"]
            })
            results.append({
                "tested_at_utc": tested_at,
                "municipality": f"{city}/{state}",
                "address_tested": f"{street}, {number}",
                "adapter": adapter.source_id,
                "connection_status": connection_status,
                "coverage_status": coverage_status,
                "records_returned": len(records),
                "fields_available": fields,
                "sample_records": summaries,
                "adapter_error": error,
                "diagnostics": diagnostics,
                "limitations": (
                    "Retorno espacial não comprova correspondência exata do endereço, "
                    "propriedade legal ou titularidade. Campos ausentes não foram inferidos."
                ),
            })
    return {
        "schema_version": 1,
        "generated_at_utc": tested_at,
        "scope": "smoke tests de quatro endereços fixos; não representa cobertura nacional",
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gera relatório verificável de cobertura cadastral municipal ao vivo."
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        help="Opcional: grava o relatório JSON neste caminho.",
    )
    args = parser.parse_args()
    report = build_report()
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report_file:
        args.report_file.parent.mkdir(parents=True, exist_ok=True)
        args.report_file.write_text(rendered + "\n", encoding="utf-8")
    failed = any(
        row["coverage_status"] in {"query_failed", "no_result"}
        for row in report["results"]
    )
    if failed:
        print(
            "LIVE MUNICIPAL TEST FAILED: consulte connection_status, adapter_error "
            "e diagnostics no relatório JSON.",
            file=sys.stderr,
        )
        return 1
    print(
        "LIVE MUNICIPAL TEST PASSED: todos os endereços de teste retornaram "
        "registro ou diagnóstico de conexão. Isso não comprova cobertura nacional."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
