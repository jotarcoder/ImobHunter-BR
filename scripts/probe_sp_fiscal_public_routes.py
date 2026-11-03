"""Inspect static PUBLIC municipal map application routes without property queries.

Only metadata of official public HTML and same-origin JS scripts is read.
No session login, authentication, captcha, tax record or personal data query.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

PUBLIC_PORTALS = {
    "Campinas": "https://zoneamento.campinas.sp.gov.br/",
    "Santo André": "https://sigamapa.santoandre.sp.gov.br/index.aspx?id=search_sql",
    "Jundiaí": "https://geo.jundiai.sp.gov.br/geojundiai/cfImob.jsp",
}
MAX_JS = 7
MAX_HTML_BYTES = 2_000_000
MAX_SCRIPT_BYTES = 1_000_000
SUSPICIOUS = ("password", "senha", "token", "oauth", "bearer", "authorization",
              "secret", "apikey", "api_key")
ROUTE_RE = re.compile(
    r'(?:(?:https://[a-z0-9.-]+)?/(?:[a-z0-9_-]+/){0,7}'
    r'[a-z0-9_-]+(?:[.]jsp|[.]aspx|[.]php|/query|/wms|/wfs|/ows))',
    re.IGNORECASE,
)


class PublicHtml(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.script_urls: list[str] = []
        self.inline_script: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        values = dict(attrs)
        src = values.get("src")
        if src:
            self.script_urls.append(src)
            self._in_script = False
        else:
            self._in_script = True

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self.inline_script.append(data[:100_000])

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False


def _official_scripts(portal: str, sources: list[str]) -> list[str]:
    host = urlsplit(portal).hostname
    out = []
    for relative in sources:
        url = urljoin(portal, relative)
        parts = urlsplit(url)
        if (parts.scheme == "https" and parts.hostname == host
                and parts.path.lower().endswith((".js", ".mjs"))):
            out.append(url)
    out = list(dict.fromkeys(out))
    return sorted(out, key=lambda url: (
        not any(word in urlsplit(url).path.casefold() for word in (
            "imob", "fiscal", "mapa", "f_pre", "/f.js", "cad", "app"
        )),
        urlsplit(url).path,
    ))[:MAX_JS]


def public_route_names(source: str) -> list[str]:
    """Only names and official public paths; no dynamic params or response values."""
    found = set()
    for match in ROUTE_RE.finditer(source[:MAX_SCRIPT_BYTES]):
        path = match.group(0).split("?", 1)[0]
        if not any(token in path.casefold() for token in SUSPICIOUS):
            found.add(path[:180])
    return sorted(found)[:55]


def probe(client: httpx.Client, city: str, portal: str) -> dict:
    report: dict = {"city": city, "portal": portal}
    try:
        resp = client.get(portal)
        if resp.is_redirect:
            return {**report, "result": "redirect_not_followed"}
        resp.raise_for_status()
        if len(resp.content) > MAX_HTML_BYTES:
            return {**report, "result": "html_above_limit"}
        parsed = PublicHtml()
        parsed.feed(resp.text)
        scripts = _official_scripts(portal, parsed.script_urls)
        report["result"] = "public_html_accessible"
        report["same_origin_script_paths"] = [urlsplit(url).path for url in scripts]
        report["inline_public_route_names"] = public_route_names(
            "\n".join(parsed.inline_script)
        )
        details = []
        for url in scripts:
            try:
                response = client.get(url)
                if response.is_redirect:
                    details.append({
                        "script_path": urlsplit(url).path,
                        "status": "redirect_not_followed",
                    })
                    continue
                response.raise_for_status()
                if len(response.content) > MAX_SCRIPT_BYTES:
                    details.append({
                        "script_path": urlsplit(url).path,
                        "status": "script_above_limit",
                    })
                    continue
                details.append({
                    "script_path": urlsplit(url).path,
                    "status": "public_script_accessible",
                    "public_route_names": public_route_names(response.text),
                })
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                details.append({
                    "script_path": urlsplit(url).path,
                    "error_type": type(exc).__name__,
                })
        report["scripts"] = details
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        report["result"] = "source_unavailable"
        report["error_type"] = type(exc).__name__
    return report


def main() -> None:
    with httpx.Client(
        timeout=httpx.Timeout(7.0), follow_redirects=False,
        headers={"User-Agent": "ImobHunter-BR/official-public-route-discovery"},
    ) as client:
        result = [
            probe(client, city, portal)
            for city, portal in PUBLIC_PORTALS.items()
        ]
    for entry in result:
        print(json.dumps(entry, ensure_ascii=False))
    with open("sp-public-fiscal-route-metadata.json", "w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
