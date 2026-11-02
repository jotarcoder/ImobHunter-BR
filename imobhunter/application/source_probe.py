"""Bounded, read-only municipal service connectivity probes.

These requests check capabilities/metadata, NEVER availability of a property,
registration number, or owner. Caller runs them off the Qt GUI thread.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Mapping
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True)
class EndpointProbe:
    state: str
    message: str
    latency_ms: int


def is_official_service_url(raw: str) -> bool:
    uri = urlparse(raw)
    host = (uri.hostname or "").casefold()
    return (
        uri.scheme == "https"
        and (host.endswith(".gov.br") or host == "gov.br")
        and not uri.username and not uri.password
    )


def _probe(client: httpx.Client, source: Mapping[str, str]) -> str:
    url, kind = source["url"], source["kind"]
    if kind == "wfs":
        # Match the production WFS version negotiation. GeoSampa requests
        # 1.0.0; other cities prefer 2.0.0 and retry 403 on older versions.
        versions = (
            ("1.0.0",) if source.get("id") == "sao_paulo"
            else ("2.0.0", "1.1.0", "1.0.0")
        )
        for index, version in enumerate(versions):
            try:
                response = client.get(
                    url, params={
                        "service": "WFS",
                        "version": version,
                        "request": "GetCapabilities",
                    },
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 403 and index < len(versions) - 1:
                    continue
                raise
            try:
                root = ElementTree.fromstring(response.text)
            except ElementTree.ParseError as exc:
                raise ValueError("O servidor não retornou XML WFS válido.") from exc
            root_name = root.tag.rsplit("}", 1)[-1]
            if root_name != "WFS_Capabilities":
                raise ValueError(f"Resposta inesperada do WFS: {root_name}.")
            if source.get("id") == "sao_paulo" and "geoportal:lote_cidadao" not in response.text:
                raise ValueError("A camada cadastral do GeoSampa não foi anunciada.")
            return f"GetCapabilities WFS {version} respondeu com XML válido"
    if kind == "arcgis":
        response = client.get(url, params={"f": "json"})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or "error" in body:
            raise ValueError("ArcGIS REST respondeu com erro ou metadados inválidos.")
        if not any(key in body for key in ("fields", "layers", "name", "serviceDescription", "geometryType")):
            raise ValueError("ArcGIS REST não retornou descrição reconhecida da camada.")
        return "Metadados ArcGIS REST responderam corretamente"
    if kind == "ckan":
        response = client.get(url)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("success") is not True:
            raise ValueError("O portal CKAN não confirmou success=true.")
        return "API do catálogo CKAN respondeu"
    raise ValueError(f"Protocolo municipal desconhecido: {kind}")


def probe_endpoint(
    source: Mapping[str, str], client: httpx.Client | None = None
) -> EndpointProbe:
    """Connectivity diagnosis only; TLS verification is never bypassed."""
    url = source.get("url", "")
    if not is_official_service_url(url):
        return EndpointProbe("error", "URL precisa ser HTTPS oficial gov.br.", 0)
    start = monotonic()
    try:
        if client is None:
            with httpx.Client(
                timeout=httpx.Timeout(TIMEOUT_SECONDS, connect=4.0),
                follow_redirects=True,
            ) as managed:
                message = _probe(managed, source)
        else:
            message = _probe(client, source)
        return EndpointProbe("responded", message, int((monotonic() - start) * 1000))
    except httpx.TimeoutException as exc:
        return EndpointProbe(
            "timeout", f"{type(exc).__name__}: serviço não respondeu no limite configurado",
            int((monotonic() - start) * 1000),
        )
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        detail = str(exc).replace("\n", " ").strip()
        return EndpointProbe(
            "error", f"{type(exc).__name__}: {detail[:180]}",
            int((monotonic() - start) * 1000),
        )
