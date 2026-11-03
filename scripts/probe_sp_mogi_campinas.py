"""Discover official public GIS metadata without querying personal property records."""
from __future__ import annotations

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
        if parsed.scheme == "https" and parsed.hostname == host:
            if parsed.path.lower().endswith((".js", ".mjs")):
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
                    line, flags=re.I,
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


def main() -> None:
    with httpx.Client(
        timeout=httpx.Timeout(8.0), follow_redirects=True,
        headers={"User-Agent": "ImobHunter-BR/municipal-public-metadata"},
    ) as client:
        results = (
            probe_site(client, "Mogi das Cruzes", MOGI_MAP)
            + probe_ckan(client)
            + probe_site(client, "Campinas", CAMPINAS_METADATA)
            + probe_site(client, "Campinas", CAMPINAS_INFO)
        )
    for row in results:
        print(json.dumps(row, ensure_ascii=False))
    with open("sp-mogi-campinas-public-sources.json", "w", encoding="utf-8") as stream:
        json.dump(results, stream, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
