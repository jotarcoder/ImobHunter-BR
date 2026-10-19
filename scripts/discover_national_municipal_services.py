from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import httpx

from imobhunter.sources.inde import DEFAULT_INDE_CSW_ENDPOINT, GeospatialService, INDECatalog

SEARCH_TERMS = (
    "cadastro imobiliário municipal lote quadra",
    "parcelas cadastrais prefeitura",
    "lotes fiscais município",
    "cadastro territorial urbano",
)
CADASTRAL_TERMS = (
    "cadastro", "imobili", "lote", "parcela", "quadra", "territorial",
    "iptu", "inscricao", "inscrição", "imovel", "imóvel",
)
USER_AGENT = "ImobHunter-BR/0.1.19 (national municipal service discovery)"


def is_official_https(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold().rstrip(".")
    return parsed.scheme == "https" and (
        host == "gov.br" or host.endswith(".gov.br")
    )


def _candidate(service: GeospatialService) -> bool:
    text = " ".join((service.title, service.provider or "", *service.keywords)).casefold()
    return any(term in text for term in CADASTRAL_TERMS)


def _wfs_layers(xml: str) -> list[dict[str, str]]:
    root = ET.fromstring(xml)
    layers: list[dict[str, str]] = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].casefold() != "featuretype":
            continue
        values: dict[str, str] = {}
        for child in node:
            key = child.tag.rsplit("}", 1)[-1].casefold()
            if key in {"name", "title"} and child.text:
                values[key] = child.text.strip()
        if values.get("name"):
            label = (values.get("name", "") + " " + values.get("title", "")).casefold()
            if any(term in label for term in CADASTRAL_TERMS):
                layers.append({"name": values["name"], "title": values.get("title", values["name"])})
    return layers[:30]


def probe_service(
    service: GeospatialService,
    *,
    client: httpx.Client,
) -> dict[str, Any]:
    url = (service.url or "").strip()
    result: dict[str, Any] = {
        "service_id": service.service_id,
        "title": service.title,
        "provider": service.provider,
        "service_type": service.service_type,
        "url": url or None,
        "state": service.state,
        "city": service.city,
        "keywords": list(service.keywords),
        "status": "not_tested",
        "layers": [],
        "diagnostic": None,
    }
    if not _candidate(service):
        result["status"] = "not_cadastral_candidate"
        return result
    if not is_official_https(url):
        result["status"] = "rejected_unverified_host"
        result["diagnostic"] = "Endpoint ignorado: exige HTTPS em domínio gov.br."
        return result

    service_type = (service.service_type or "").upper()
    try:
        if "WFS" in service_type or url.lower().endswith("/wfs"):
            response = client.get(url, params={
                "service": "WFS", "version": "2.0.0", "request": "GetCapabilities"
            }, follow_redirects=False)
            response.raise_for_status()
            layers = _wfs_layers(response.text)
            result["layers"] = layers
            result["status"] = "cadastral_layer_found" if layers else "connected_no_cadastral_layer"
        elif "ARCGIS" in service_type or "FEATURESERVER" in url.upper() or "MAPSERVER" in url.upper():
            response = client.get(url, params={"f": "json"}, follow_redirects=False)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("error"):
                raise ValueError("Resposta ArcGIS REST inválida ou com erro.")
            layers = payload.get("layers") or []
            result["layers"] = [
                {"id": item.get("id"), "name": item.get("name")}
                for item in layers if isinstance(item, dict)
                and any(term in str(item.get("name", "")).casefold() for term in CADASTRAL_TERMS)
            ][:30]
            result["status"] = "cadastral_layer_found" if result["layers"] else "connected_no_cadastral_layer"
        else:
            result["status"] = "connected_unclassified_service"
            result["diagnostic"] = "Endpoint oficial encontrado, mas o protocolo não é validado automaticamente."
    except (httpx.HTTPError, ValueError, json.JSONDecodeError, ET.ParseError) as exc:
        result["status"] = "connection_failed"
        result["diagnostic"] = f"{type(exc).__name__}: {str(exc)[:240]}"
    return result


def discover(
    *,
    endpoint: str = DEFAULT_INDE_CSW_ENDPOINT,
    timeout: float = 8.0,
    max_records: int = 50,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    owned = client is None
    http = client or httpx.Client(
        timeout=httpx.Timeout(timeout), follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    started = datetime.now(UTC).isoformat()
    try:
        found: dict[str, GeospatialService] = {}
        query_errors: list[dict[str, str]] = []
        for term in SEARCH_TERMS:
            try:
                for service in INDECatalog.search_remote(
                    term, endpoint=endpoint, client=http, max_records=max_records
                ):
                    key = service.service_id or service.url or service.title
                    found.setdefault(key, service)
            except (RuntimeError, ValueError, httpx.HTTPError) as exc:
                query_errors.append({"term": term, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
        services = sorted(found.values(), key=lambda item: (item.title.casefold(), item.service_id))
        results = [probe_service(service, client=http) for service in services]
        return {
            "schema_version": 1,
            "generated_at_utc": started,
            "catalog": endpoint,
            "scope": "descoberta e validação inicial; não comprova cobertura nacional nem consulta cadastral por endereço",
            "queries": list(SEARCH_TERMS),
            "query_errors": query_errors,
            "services_discovered": len(services),
            "services": results,
            "summary": {
                status: sum(row["status"] == status for row in results)
                for status in sorted({row["status"] for row in results})
            },
        }
    finally:
        if owned:
            http.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Descobre e testa endpoints geoespaciais municipais oficiais no catálogo INDE."
    )
    parser.add_argument("--report-file", type=Path, help="Grava o relatório JSON neste caminho.")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--max-records", type=int, default=50)
    parser.add_argument("--endpoint", default=DEFAULT_INDE_CSW_ENDPOINT)
    args = parser.parse_args()
    if not 1 <= args.max_records <= 100 or not 1 <= args.timeout <= 30:
        parser.error("--max-records deve ser 1..100 e --timeout deve ser 1..30 segundos.")
    report = discover(endpoint=args.endpoint, timeout=args.timeout, max_records=args.max_records)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report_file:
        args.report_file.parent.mkdir(parents=True, exist_ok=True)
        args.report_file.write_text(rendered + "\n", encoding="utf-8")
    # A catalog/network outage is reported, but does not make deterministic CI red.
    if report["query_errors"] and not report["services_discovered"]:
        print("INDE discovery unavailable; diagnostics were written to the report.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
