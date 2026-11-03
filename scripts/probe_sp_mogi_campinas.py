"""Discover official public GIS metadata without querying personal property records."""
from __future__ import annotations

import csv
import io
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

MOGI_MAP = "https://geomogi.mogidascruzes.sp.gov.br/mapa"
MOGI_CKAN = "https://dados.mogidascruzes.sp.gov.br/api/3/action/package_search"
CAMPINAS_METADATA = "https://campinas.sp.gov.br/sites/metadadosgeoespaciais"
CAMPINAS_INFO = "https://portal-adm.campinas.sp.gov.br/servico/consultar-metadados-espaciais"
MAX_BYTES = 2_000_000
MAX_SCRIPTS = 9
KEYWORDS = ("lote", "quadra", "inscri", "fiscal", "cadastr", "logradouro",
            "setor", "geo", "wfs", "wms", "layer")


class HTMLAssets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.scripts.append(values["src"] or "")
        if tag == "link" and values.get("href"):
            self.links.append(values["href"] or "")


def request_text(client: httpx.Client, url: str, params: dict | None = None) -> str:
    response = client.get(url, params=params)
    response.raise_for_status()
    if len(response.content) > MAX_BYTES:
        raise ValueError("Metadata response larger than safe limit")
    return response.text


def safe_source_scripts(base_url: str, sources: list[str]) -> list[str]:
    host = urlparse(base_url).hostname
    selected = []
    for source in sources:
        url = urljoin(base_url, source)
        parsed = urlparse(url)
        if (parsed.scheme == "https" and parsed.hostname == host
                and parsed.path.lower().endswith((".js", ".mjs"))):
            selected.append(url)
    return list(dict.fromkeys(selected))[:MAX_SCRIPTS]


def script_metadata(content: str) -> dict:
    paths = []
    for line in content.splitlines():
        lower = line.casefold()
        if any(t in lower for t in KEYWORDS) and any(
            m in lower for m in ("url:", "fetch(", "axios.", "/api/", "wfs", "wms", "route")
        ) and not any(s in lower for s in (
            "token", "senha", "password", "authorization", "bearer"
        )):
            paths.extend(
                match.split("?", 1)[0] for match in re.findall(
                    r"[\w./:-]{3,120}(?:/wfs|/wms|/ows|/api/|/query|\.php|\.jsp)[\w./:-]{0,80}",
                    line, flags=re.IGNORECASE,
                )
            )
        if len(paths) >= 25:
            break
    return {"public_route_hints": sorted(set(paths))[:25]}


def probe_site(client: httpx.Client, city: str, url: str) -> list[dict]:
    output = []
    try:
        html = request_text(client, url)
        parser = HTMLAssets()
        parser.feed(html)
        scripts = safe_source_scripts(url, parser.scripts)
        output.append({
            "city": city, "source": "public_html", "url": url,
            "script_paths": [urlparse(s).path for s in scripts],
            "link_count": len(parser.links),
            "mentions_fiscal_search": any(
                token in html.casefold() for token in ("pesquisa de lote", "inscri", "quadras")
            ),
        })
        for script in scripts:
            try:
                content = request_text(client, script)
                output.append({
                    "city": city, "source": "public_js_routes",
                    "path": urlparse(script).path, **script_metadata(content),
                })
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                output.append({
                    "city": city, "source": "public_js_routes",
                    "path": urlparse(script).path, "error_type": type(exc).__name__,
                })
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        output.append({
            "city": city, "source": "public_html", "url": url,
            "error_type": type(exc).__name__,
        })
    return output


def probe_ckan(client: httpx.Client) -> list[dict]:
    output = []
    for keyword in ("cadastro imobiliario", "lotes", "quadras", "inscricao", "logradouro"):
        try:
            payload = json.loads(request_text(client, MOGI_CKAN, {
                "q": keyword, "rows": "8",
            }))
            if not isinstance(payload, dict) or not payload.get("success"):
                raise ValueError("Invalid public CKAN catalogue metadata")
            data = payload.get("result") or {}
            datasets = data.get("results") or []
            output.append({
                "city": "Mogi das Cruzes", "source": "ckan_public_catalogue",
                "query": keyword, "total": data.get("count"),
                "datasets": [{
                    "title": p.get("title"), "slug": p.get("name"),
                    "resource_formats": [
                        x.get("format") for x in (p.get("resources") or [])[:6]
                    ],
                } for p in datasets[:8] if isinstance(p, dict)],
            })
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            output.append({
                "city": "Mogi das Cruzes", "source": "ckan_public_catalogue",
                "query": keyword, "error_type": type(exc).__name__,
            })
    return output



MOGI_CKAN_SHOW = "https://dados.mogidascruzes.sp.gov.br/api/3/action/package_show"


def _official_resource_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    url = urlparse(value)
    host = url.hostname or ""
    return (
        url.scheme == "https" and url.username is None and url.password is None
        and (host == "mogidascruzes.sp.gov.br"
             or host.endswith(".mogidascruzes.sp.gov.br"))
    )


def _csv_header_only(client: httpx.Client, url: str) -> dict:
    """Read up to 4096 bytes of a public CSV: log column names, not records."""
    if not _official_resource_url(url):
        return {"status": "untrusted_external_resource_host"}
    try:
        with client.stream("GET", url, headers={"Range": "bytes=0-4095"},
                           follow_redirects=False) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                return {"status": "redirect_not_followed"}
            response.raise_for_status()
            chunks = bytearray()
            for chunk in response.iter_bytes(chunk_size=1024):
                chunks.extend(chunk[:4096 - len(chunks)])
                if len(chunks) >= 4096 or b"\n" in chunks:
                    break
        if chunks[:2] == b"PK":
            return {"status": "compressed_file_not_scanned"}
        if b"\n" not in chunks:
            return {"status": "header_exceeds_bounded_read"}
        line = bytes(chunks).split(b"\n", 1)[0].decode("utf-8-sig", errors="replace")
        if len(line) > 3500:
            return {"status": "header_exceeds_safe_limit"}
        sep = ";" if line.count(";") > line.count(",") else ","
        columns = next(csv.reader(io.StringIO(line), delimiter=sep), [])
        return {
            "status": "public_csv_header",
            "column_count": len(columns),
            "column_names_only": [c.strip()[:80] for c in columns[:75]],
        }
    except (httpx.HTTPError, ValueError, TypeError, csv.Error) as exc:
        return {"status": "source_error", "error_type": type(exc).__name__}


def probe_mogi_cadastre_metadata(client: httpx.Client) -> list[dict]:
    """CKAN package metadata and at most three public CSV headers, no rows."""
    output = []
    for slug in ("cadastro-imobiliario", "lista-de-logradouros-visao-financas"):
        try:
            payload = json.loads(request_text(client, MOGI_CKAN_SHOW, {"id": slug}))
            if not isinstance(payload, dict) or not payload.get("success"):
                raise ValueError("No public dataset metadata")
            dataset = payload.get("result") or {}
            resources = dataset.get("resources") or []
            entry = {
                "city": "Mogi das Cruzes", "source": "ckan_dataset_resources",
                "slug": slug, "title": dataset.get("title"),
                "modified": dataset.get("metadata_modified"),
                "license_id": dataset.get("license_id"),
                "resource_count": len(resources),
                "resources": [],
            }
            for resource in resources[:16]:
                if not isinstance(resource, dict):
                    continue
                description = {
                    "name": resource.get("name"),
                    "format": resource.get("format"),
                    "size": resource.get("size"),
                    "last_modified": resource.get("last_modified"),
                    "created": resource.get("created"),
                    "official_host": _official_resource_url(resource.get("url")),
                }
                entry["resources"].append(description)
            public_csv = [
                resource for resource in resources
                if isinstance(resource, dict)
                and str(resource.get("format") or "").casefold() == "csv"
                and _official_resource_url(resource.get("url"))
            ]
            entry["resource_years"] = sorted({
                int(year)
                for resource in public_csv
                for year in re.findall(
                    r"20[0-2][0-9]", str(resource.get("name") or "")
                )
            })
            entry["recent_resource_names"] = [
                resource.get("name")
                for resource in public_csv
                if any(t in str(resource.get("name") or "").lower() for t in (
                    "2024", "2025", "2026"
                ))
            ][:35]
            csv_resources = []
            for prefix in ("pmmc_imobiliario_", "pmmc_iptu_", "iptu_itbi_"):
                choices = [
                    res for res in public_csv
                    if re.fullmatch(
                        re.escape(prefix) + r"20[0-2][0-9](?:_part1)?[.]csv",
                        str(res.get("name") or ""), flags=re.IGNORECASE,
                    )
                ]
                if choices:
                    csv_resources.append(max(
                        choices,
                        key=lambda res: str(res.get("name") or ""),
                    ))
            if not csv_resources:
                csv_resources = public_csv[:3]
            entry["selected_schema_resources"] = [
                res.get("name") for res in csv_resources
            ]
            entry["csv_public_schemas"] = [
                {
                    "resource_name": resource.get("name"),
                    **_csv_header_only(client, resource["url"]),
                }
                for resource in csv_resources
            ]
            output.append(entry)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            output.append({
                "city": "Mogi das Cruzes", "source": "ckan_dataset_resources",
                "slug": slug, "error_type": type(exc).__name__,
            })
    return output


def main() -> None:
    with httpx.Client(
        timeout=httpx.Timeout(8.0), follow_redirects=True,
        headers={"User-Agent": "ImobHunter-BR/municipal-public-metadata"},
    ) as client:
        results = (
            probe_site(client, "Mogi das Cruzes", MOGI_MAP)
            + probe_ckan(client)
            + probe_mogi_cadastre_metadata(client)
            + probe_site(client, "Campinas", CAMPINAS_METADATA)
            + probe_site(client, "Campinas", CAMPINAS_INFO)
        )
    for row in results:
        print(json.dumps(row, ensure_ascii=False))
    with open("sp-mogi-campinas-public-sources.json", "w", encoding="utf-8") as stream:
        json.dump(results, stream, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
