"""Read-only discovery of public municipal GIS metadata (SP, stage 4).

Ribeirão Preto: official ArcGIS REST public service/layer schema.
São José dos Campos: Geosanja public WFS and website publication links.

No owner/taxpayer records, credentials, authentication bypass, downloads
of entire datasets, or candidate-to-property identity claims.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

RIBEIRAO_REST = "https://webgis.ribeiraopreto.sp.gov.br/server/rest/services"
RIBEIRAO_PORTAL_SEARCH = (
    "https://webgis.ribeiraopreto.sp.gov.br/portal/sharing/rest/search"
)
SJC_PUBLIC_PORTAL = "https://geosanja.sjc.sp.gov.br/"
SJC_WFS_CANDIDATES = (
    "https://geosanja.sjc.sp.gov.br/geoserver/ows",
    "https://geosanja.sjc.sp.gov.br/geoserver/wfs",
    "https://geosanja.sjc.sp.gov.br/ows",
)
INTERESTING = (
    "lote", "quadra", "imob", "cadast", "inscri", "endereco",
    "logradouro", "fiscal", "parcela", "predial", "urbano",
)
MAX_RESPONSE = 5_000_000


class PublicScripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        properties = dict(attrs)
        if tag == "script" and properties.get("src"):
            self.scripts.append(str(properties["src"]))
        if tag == "link" and properties.get("href"):
            self.links.append(str(properties["href"]))


def http_get(client: httpx.Client, url: str, params: dict | None = None) -> httpx.Response:
    response = client.get(url, params=params)
    response.raise_for_status()
    if len(response.content) > MAX_RESPONSE:
        raise ValueError("Metadata is too large, skipping.")
    return response


def safe_error(exc: Exception) -> dict[str, str]:
    return {"error_type": type(exc).__name__}


def list_arcgis(client: httpx.Client) -> list[dict]:
    results = []
    try:
        payload = http_get(client, RIBEIRAO_REST, {"f": "json"}).json()
        if not isinstance(payload, dict):
            raise TypeError("Invalid ArcGIS service catalogue")
        services = payload.get("services") or []
        folders = payload.get("folders") or []
        results.append({
            "city": "Ribeirão Preto",
            "endpoint": RIBEIRAO_REST,
            "folders": folders[:35],
            "service_count": len(services),
            "services": [
                {"name": x.get("name"), "type": x.get("type")}
                for x in services[:100] if isinstance(x, dict)
            ],
            "requires_login": bool(payload.get("error", {}).get("code") in (401, 403))
                if isinstance(payload.get("error"), dict) else False,
        })
        # Only probe a handful of public catalogue folders; no full indexing.
        preferred = [
            folder for folder in folders
            if any(text in folder.casefold() for text in INTERESTING)
            or folder.casefold() in ("hosted", "public", "publico", "planejamento")
        ][:6]
        for folder in preferred:
            try:
                part = http_get(client, RIBEIRAO_REST + "/" + folder, {"f": "json"}).json()
                if not isinstance(part, dict):
                    raise TypeError("Invalid folder metadata")
                services = part.get("services") or []
                results.append({
                    "city": "Ribeirão Preto",
                    "folder": folder,
                    "service_count": len(services),
                    "services": [
                        {"name": x.get("name"), "type": x.get("type")}
                        for x in services[:40] if isinstance(x, dict)
                    ],
                })
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                results.append({"city": "Ribeirão Preto", "folder": folder, **safe_error(exc)})
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        results.append({"city": "Ribeirão Preto", "endpoint": RIBEIRAO_REST, **safe_error(exc)})
    try:
        search = http_get(client, RIBEIRAO_PORTAL_SEARCH, {
            "f": "json",
            "q": '(title:imoveis OR title:lotes OR title:cadastro OR title:quadra)',
            "num": "20",
            "sortField": "title",
        }).json()
        if not isinstance(search, dict):
            raise TypeError("Invalid portal search payload")
        items = search.get("results") or []
        results.append({
            "city": "Ribeirão Preto", "source": "public_portal_search",
            "total": search.get("total"),
            "items": [
                {"title": i.get("title"), "type": i.get("type"),
                 "access": i.get("access"), "url": i.get("url"),
                 "id": i.get("id")}
                for i in items[:20] if isinstance(i, dict)
            ],
        })
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        results.append({"city": "Ribeirão Preto", "source": "public_portal_search",
                        **safe_error(exc)})
    return results


def list_geosanja(client: httpx.Client) -> list[dict]:
    results = []
    try:
        response = http_get(client, SJC_PUBLIC_PORTAL)
        parsed = PublicScripts()
        parsed.feed(response.text)
        script_urls = [
            urljoin(SJC_PUBLIC_PORTAL, src)
            for src in parsed.scripts
            if urlparse(urljoin(SJC_PUBLIC_PORTAL, src)).hostname
            == "geosanja.sjc.sp.gov.br"
        ]
        results.append({
            "city": "São José dos Campos", "source": "public_geosanja_homepage",
            "http_status": response.status_code,
            "script_paths": [urlparse(x).path for x in script_urls[:32]],
            "link_paths": [
                urlparse(urljoin(SJC_PUBLIC_PORTAL, x)).path
                for x in parsed.links[:35]
            ],
        })
        # Inspect metadata references in at most 3 public local script bundles,
        # without logging their full source, tokens, values, or credentials.
        for url in script_urls[:3]:
            try:
                source = http_get(client, url).text
                matches = sorted({
                    match[:140] for match in re.findall(
                        r"[^\"'\s<>]{0,100}(?:geoserver|/wfs|/ows|geosanja)[^\"'\s<>]{0,120}",
                        source, flags=re.IGNORECASE,
                    )
                    if not any(bad in match.lower() for bad in (
                        "token", "authorization", "password", "senha",
                    ))
                })[:15]
                results.append({
                    "city": "São José dos Campos",
                    "source": "public_static_script",
                    "path": urlparse(url).path, "public_gis_hints": matches,
                })
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                results.append({"city": "São José dos Campos",
                                "source": "public_static_script",
                                "path": urlparse(url).path, **safe_error(exc)})
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        results.append({"city": "São José dos Campos",
                        "source": "public_geosanja_homepage", **safe_error(exc)})
    for endpoint in SJC_WFS_CANDIDATES:
        try:
            response = http_get(client, endpoint, {
                "service": "WFS", "request": "GetCapabilities", "version": "1.1.0",
            })
            root = ET.fromstring(response.content)
            features = []
            for node in root.iter():
                if node.tag.rsplit("}", 1)[-1] != "FeatureType":
                    continue
                name = next((
                    (x.text or "").strip() for x in node
                    if x.tag.rsplit("}", 1)[-1] == "Name"
                ), "")
                title = next((
                    (x.text or "").strip() for x in node
                    if x.tag.rsplit("}", 1)[-1] == "Title"
                ), "")
                if name and any(term in (name + title).casefold()
                                for term in INTERESTING):
                    features.append({"name": name, "title": title[:90]})
            results.append({
                "city": "São José dos Campos", "endpoint": endpoint,
                "root": root.tag, "candidate_types": features[:40],
                "candidate_count": len(features),
            })
        except (httpx.HTTPError, ValueError, TypeError, ET.ParseError) as exc:
            results.append({"city": "São José dos Campos",
                            "endpoint": endpoint, **safe_error(exc)})
    return results


def main() -> None:
    with httpx.Client(
        timeout=httpx.Timeout(8.0), follow_redirects=True,
        headers={"User-Agent": "ImobHunter-BR/2.1 official-public-schema-probe"},
    ) as client:
        results = list_arcgis(client) + list_geosanja(client)
    for result in results:
        print(json.dumps(result, ensure_ascii=False, default=str))
    with open("sp-next-public-service-discovery.json", "w", encoding="utf-8") as file:
        json.dump(results, file, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
