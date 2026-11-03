"""Bounded, public, read-only SP municipal WFS capability discovery.

No authentication, no taxpayer/owner data and no unbounded feature queries.
This script logs *schema names only*, never private field values.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

import httpx

TARGETS = {
    "Jundiai": [
        "https://geo.jundiai.sp.gov.br/geoserver/ows",
        "https://geo.jundiai.sp.gov.br/geoserver/wfs",
    ],
    "Santo Andre": [
        "https://sigamapa.santoandre.sp.gov.br/geoserver/ows",
        "https://siga.santoandre.sp.gov.br/geoserver/ows",
        "https://geoserver.santoandre.sp.gov.br/geoserver/ows",
    ],
}
INTERESTING = ("lote", "quadra", "fiscal", "imob", "endereco", "numero", "predi")
MAX_SCHEMA_LAYERS = 5


def get_xml(client: httpx.Client, url: str, params: dict[str, str]):
    response = client.get(url, params=params)
    response.raise_for_status()
    if len(response.content) > 8_000_000:
        raise ValueError("Capabilities exceeded 8 MB; skipped")
    return ET.fromstring(response.content)


def show_names(root: ET.Element, tag: str) -> list[str]:
    return [
        (elem.text or "").strip()
        for elem in root.iter()
        if elem.tag.rsplit("}", 1)[-1].casefold() == tag.casefold()
        and elem.text and elem.text.strip()
    ]


def inspect(client: httpx.Client, city: str, endpoint: str) -> dict:
    result = {"city": city, "endpoint": endpoint}
    try:
        root = get_xml(client, endpoint, {
            "service": "WFS", "version": "1.1.0", "request": "GetCapabilities",
        })
        feature_names = [
            (element.text or "").strip()
            for ft in root.iter()
            if ft.tag.rsplit("}", 1)[-1] == "FeatureType"
            for element in ft
            if element.tag.rsplit("}", 1)[-1] == "Name" and element.text
        ]
        # The Santo André municipality uses numeric/opaque layer names.
        # Use the public WFS Title metadata to identify cadastral candidates.
        feature_meta = []
        for ft in root.iter():
            if ft.tag.rsplit("}", 1)[-1] != "FeatureType":
                continue
            name = next((
                (c.text or "").strip()
                for c in ft if c.tag.rsplit("}", 1)[-1] == "Name"
            ), "")
            title = next((
                (c.text or "").strip()
                for c in ft if c.tag.rsplit("}", 1)[-1] == "Title"
            ), "")
            if name:
                feature_meta.append({"name": name, "title": title[:120]})
        selected = [
            feature["name"] for feature in feature_meta
            if any(token in (feature["name"] + " " + feature["title"]).casefold()
                   for token in INTERESTING)
        ]
        result.update({
            "feature_type_count": len(feature_names),
            "candidate_types": selected[:35],
            "candidate_metadata": [
                item for item in feature_meta if item["name"] in selected[:35]
            ],
            "first_feature_names": feature_meta[:45],
            "capabilities_root": root.tag,
        })
        for typename in selected[:MAX_SCHEMA_LAYERS]:
            try:
                schema = get_xml(client, endpoint, {
                    "service": "WFS", "version": "1.1.0",
                    "request": "DescribeFeatureType", "typeName": typename,
                })
                raw_fields = [
                    node.attrib.get("name")
                    for node in schema.iter()
                    if node.tag.rsplit("}", 1)[-1] == "element"
                    and node.attrib.get("name")
                ]
                result.setdefault("schema", {})[typename] = raw_fields[:90]
            except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
                result.setdefault("schema_errors", {})[typename] = type(exc).__name__
    except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
        result["error"] = type(exc).__name__
        result["detail"] = str(exc).split("\n", 1)[0][:180]
    # WMS map services can expose layers omitted by anonymous WFS.
    # Record layer metadata only; never query identities via GetFeatureInfo.
    try:
        root = get_xml(client, endpoint, {
            "service": "WMS", "version": "1.3.0", "request": "GetCapabilities",
        })
        layers = []
        for layer in root.iter():
            if layer.tag.rsplit("}", 1)[-1] != "Layer":
                continue
            name = next((
                (c.text or "").strip()
                for c in layer if c.tag.rsplit("}", 1)[-1] == "Name"
            ), "")
            title = next((
                (c.text or "").strip()
                for c in layer if c.tag.rsplit("}", 1)[-1] == "Title"
            ), "")
            if name and any(
                part in (name + " " + title).casefold() for part in INTERESTING
            ):
                layers.append({
                    "name": name, "title": title[:130],
                    "queryable": layer.attrib.get("queryable", "inherited"),
                })
        result["wms_cadastral_layers"] = layers[:40]
    except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
        result["wms_error"] = type(exc).__name__
    return result


def main() -> None:
    results = []
    with httpx.Client(
        timeout=httpx.Timeout(9.0), follow_redirects=True,
        headers={"User-Agent": "ImobHunter-BR/2.1 source-schema-audit"},
    ) as client:
        for city, endpoints in TARGETS.items():
            for endpoint in endpoints:
                result = inspect(client, city, endpoint)
                results.append(result)
                print(json.dumps(result, ensure_ascii=False))
        for city, page in (
            ("Santo Andre", "https://sigamapa.santoandre.sp.gov.br/"),
            ("Jundiai", "https://geo.jundiai.sp.gov.br/geojundiai/cfImob.jsp"),
        ):
            try:
                response = client.get(page)
                response.raise_for_status()
                html = response.text[:800_000]
                # Only inspect public static script paths, never tokens or
                # private application payloads.
                scripts = re.findall(
                    r'<script[^>]+src=[\x22\x27]([^\x22\x27]+)', html,
                    flags=re.IGNORECASE,
                )
                endpoints = sorted(set(re.findall(
                    r'[^\s\x22\x27<>()]{0,75}(?:geoserver|WMS|wfs|fiscal|lote)[^\s\x22\x27<>()]{0,75}',
                    html,
                    flags=re.IGNORECASE,
                )))[:18]
                item = {
                    "city": city, "public_html_page": page, "http_status": response.status_code,
                    "static_script_paths": scripts[:45],
                    "public_html_geo_hints": endpoints,
                }
            except httpx.HTTPError as exc:
                item = {"city": city, "public_html_page": page, "error": type(exc).__name__}
            results.append(item)
            print(json.dumps(item, ensure_ascii=False))
    with open("sp-municipal-public-schema.json", "w", encoding="utf-8") as file:
        json.dump(results, file, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
