from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from imobhunter.application.address_geocoding import CachedAddressGeocoder
from imobhunter.application.cadastral_map import prepare_features
from imobhunter.domain.models import SearchRequest
from imobhunter.sources.geosampa import GeoSampaAdapter
from imobhunter.sources.official_municipal_services import OfficialMunicipalServicesAdapter


CASES = [
    {
        "municipality": "São Paulo capital/SP",
        "address": "Avenida Paulista",
        "number": "1000",
        "city": "São Paulo",
        "state": "SP",
        "adapter": "geosampa",
    },
    {
        "municipality": "Praia Grande/SP",
        "address": "Avenida Presidente Costa e Silva",
        "number": "",
        "city": "Praia Grande",
        "state": "SP",
        "adapter": "official_municipal",
    },
    {
        "municipality": "Rio de Janeiro/RJ",
        "address": "Avenida Rio Branco",
        "number": "1",
        "city": "Rio de Janeiro",
        "state": "RJ",
        "adapter": "official_municipal",
    },
    {
        "municipality": "Belo Horizonte/MG",
        "address": "Praça Sete de Setembro",
        "number": "",
        "city": "Belo Horizonte",
        "state": "MG",
        "adapter": "official_municipal",
    },
    {
        "municipality": "Santos/SP",
        "address": "Praça Visconde de Mauá",
        "number": "",
        "city": "Santos",
        "state": "SP",
        "adapter": "official_municipal",
    },
    {
        "municipality": "Bertioga/SP",
        "address": "Avenida Anchieta",
        "number": "1000",
        "city": "Bertioga",
        "state": "SP",
        "adapter": "official_municipal",
    },
    {
        "municipality": "Brasília/DF",
        "address": "SQN 100",
        "number": "",
        "city": "Brasília",
        "state": "DF",
        "adapter": "official_municipal",
    },
    {
        "municipality": "Goiânia/GO",
        "address": "Avenida Goiás",
        "number": "1",
        "city": "Goiânia",
        "state": "GO",
        "adapter": "official_municipal",
    },
    {
        "municipality": "Blumenau/SC",
        "address": "Rua XV de Novembro",
        "number": "100",
        "city": "Blumenau",
        "state": "SC",
        "adapter": "official_municipal",
    },
    {
        "municipality": "Joinville/SC — Condeixa 2550",
        "address": "Avenida Aluísio Pires Condeixa",
        "number": "2550",
        "city": "Joinville",
        "state": "SC",
        "adapter": "official_municipal",
    },
    {
        "municipality": "São Bento do Sul/SC — Benjamin Constant 118",
        "address": "Rua Benjamin Constant",
        "number": "118",
        "city": "São Bento do Sul",
        "state": "SC",
        "adapter": "official_municipal",
    },
    {
        "municipality": "São Bento do Sul/SC — Jorge Lacerda 75",
        "address": "Rua Jorge Lacerda",
        "number": "75",
        "city": "São Bento do Sul",
        "state": "SC",
        "adapter": "official_municipal",
    },
    {
        "municipality": "Juiz de Fora/MG — Avenida Brasil 2001",
        "address": "Avenida Brasil",
        "number": "2001",
        "city": "Juiz de Fora",
        "state": "MG",
        "adapter": "official_municipal",
    },
    {
        "municipality": "Recife/PE",
        "address": "Avenida Conde da Boa Vista",
        "number": "100",
        "city": "Recife",
        "state": "PE",
        "adapter": "official_municipal",
    },
    {
        "municipality": "Porto Alegre/RS — Ipiranga 6681",
        "address": "Avenida Ipiranga",
        "number": "6681",
        "city": "Porto Alegre",
        "state": "RS",
        "adapter": "official_municipal",
    },
    {
        "municipality": "Porto Alegre/RS — Praça da Matriz 101",
        "address": "Praça Marechal Deodoro",
        "number": "101",
        "city": "Porto Alegre",
        "state": "RS",
        "adapter": "official_municipal",
    },
]


def safe_record(record: Any) -> dict[str, Any]:
    attributes = getattr(record, "attributes", {}) or {}
    source_properties = attributes.get("source_properties")
    map_features = prepare_features((record,))
    geometry = map_features[0] if map_features else None
    return {
        "address": getattr(record, "address", None),
        "city": getattr(record, "city", None),
        "state": getattr(record, "state", None),
        "sql": attributes.get("sql"),
        "iptu_registration_number": attributes.get("iptu_registration_number"),
        "iptu_ciu": attributes.get("iptu_ciu"),
        "block": getattr(record, "block", None),
        "lot": getattr(record, "lot", None),
        "area_m2": getattr(record, "area_m2", None),
        "built_area_m2": attributes.get("built_area_m2"),
        "geometry_returned": bool(attributes.get("geometry_geojson")),
        "map_renderable": geometry is not None,
        "valid_cadastral_polygon": bool(geometry and geometry.has_official_polygon),
        "map_classification": geometry.classification if geometry else None,
        "cadastre_match": attributes.get("cadastre_match"),
        "sql_status": attributes.get("sql_status"),
        "iptu_status": attributes.get("iptu_status"),
        "official_source": attributes.get("official_source", attributes.get("source")),
        "service_url": attributes.get("service_url"),
        "returned_field_names": sorted(str(k) for k in source_properties) if isinstance(source_properties, dict) else sorted(str(k) for k in attributes),
    }


def main() -> None:
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="imobhunter-cadastral-evidence-") as temp_dir:
        root = Path(temp_dir)
        geocoder = CachedAddressGeocoder(
            root / "geocoding.sqlite3",
            user_agent="ImobHunter-BR-cadastral-evidence/0.1 (official source validation)",
            minimum_interval=1.2,
        )
        municipal_adapter = OfficialMunicipalServicesAdapter(
            cache_dir=root / "municipal-cache",
            geocoder=geocoder,
            timeout=18.0,
        )
        geosampa_adapter = GeoSampaAdapter(timeout=20.0, geocoder=geocoder)

        for index, case in enumerate(CASES):
            if index:
                time.sleep(1.2)
            request = SearchRequest(
                address=case["address"],
                number=case["number"],
                city=case["city"],
                state=case["state"],
            )
            adapter = geosampa_adapter if case["adapter"] == "geosampa" else municipal_adapter
            item: dict[str, Any] = {
                **case,
                "query": " ".join(part for part in (case["address"], case["number"], case["city"], case["state"]) if part),
                "records": [],
                "record_count": 0,
                "sql_count": 0,
                "map_polygon_count": 0,
                "map_renderable_count": 0,
                "geocoded_spatial_match_count": 0,
                "status": "not_verified",
                "diagnostics": {},
                "errors": {},
            }
            try:
                records = adapter.search(request)
                item["records"] = [safe_record(record) for record in records]
                item["record_count"] = len(records)
                item["sql_count"] = sum(
                    1 for record in item["records"]
                    if record.get("sql") or record.get("iptu_registration_number")
                )
                item["map_polygon_count"] = sum(
                    bool(record["valid_cadastral_polygon"]) for record in item["records"]
                )
                item["map_renderable_count"] = sum(
                    bool(record["map_renderable"]) for record in item["records"]
                )
                item["geocoded_spatial_match_count"] = sum(
                    record["map_classification"] in {"exact", "spatial_match", "parcel_query_match"}
                    for record in item["records"]
                )
                item["status"] = "sql_returned" if item["sql_count"] else (
                    "records_without_sql" if records else "zero_records"
                )
            except Exception as exc:  # noqa: BLE001 - preserve each endpoint failure in the evidence report.
                item["status"] = "request_error"
                item["errors"]["exception"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            if hasattr(adapter, "last_diagnostics"):
                item["diagnostics"] = dict(
                    adapter.last_diagnostics.get(case["city"], {})
                )
            if hasattr(adapter, "last_geocoded"):
                item["diagnostics"]["geocoding"] = adapter.last_geocoded.get(
                    case["city"]
                )
            if hasattr(adapter, "last_errors"):
                error = adapter.last_errors.get(case["city"])
                if error:
                    item["errors"]["municipal_source"] = error
            if item["errors"]:
                item["status"] = "source_error"
            results.append(item)
            print(
                f'{item["municipality"]}: status={item["status"]}; '
                f'records={item["record_count"]}; SQL/inscrição={item["sql_count"]}; '
                f'polígonos={item["map_polygon_count"]}'
            )
            for record in item["records"][:3]:
                print(
                    f'  SQL={record.get("sql") or record.get("iptu_registration_number")!r}; '
                    f'quadra={record.get("block")!r}; lote={record.get("lot")!r}; '
                    f'area_m2={record.get("area_m2")!r}; geometry={record.get("geometry_returned")}; '
                    f'source={record.get("official_source")!r}'
                )
            if item["errors"]:
                print(f'  errors={json.dumps(item["errors"], ensure_ascii=False)}')
            if case["city"] == "Juiz de Fora":
                print(
                    "  juiz_diagnostics="
                    + json.dumps(item["diagnostics"], ensure_ascii=False, default=str)[:3000]
                )
            if case["city"] in {"Joinville", "São Bento do Sul"}:
                print(
                    "  sc_diagnostics="
                    + json.dumps(item["diagnostics"], ensure_ascii=False, default=str)[:3000]
                )
            if case["city"] == "Porto Alegre":
                print(
                    "  porto_alegre_diagnostics="
                    + json.dumps(item["diagnostics"], ensure_ascii=False, default=str)[:4000]
                )

    report = {
        "purpose": "Live municipal cadastral evidence; geocoding alone is not cadastral proof.",
        "rule": "SQL is considered returned only when the real response contains a non-empty SQL or iptu_registration_number field. A connection failure is never absence of a registered property.",
        "results": results,
    }
    output = Path("municipal-cadastral-evidence.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Evidence report written to {output}")
    print("No SQL claim is inferred from a geocoded address, a nearby geometry, or a mocked unit test.")


if __name__ == "__main__":
    main()
