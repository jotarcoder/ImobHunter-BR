from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


@dataclass(frozen=True)
class GeospatialService:
    service_id: str
    title: str
    provider: str | None = None
    service_type: str | None = None
    url: str | None = None
    layer: str | None = None
    keywords: tuple[str, ...] = ()
    state: str | None = None
    city: str | None = None
    updated_at: str | None = None


DEFAULT_INDE_CSW_ENDPOINT = "https://metadados.inde.gov.br/geonetwork/srv/por/csw"


class INDECatalog:
    """Reads an authorized INDE catalog export for geoservice discovery.

    INDE is a discovery/catalog layer for OGC geoservices (WMS/WFS/WCS),
    not a property-record source. The catalog is intentionally kept outside
    PropertyRecord reconciliation.
    """

    def __init__(self, data_path: str | Path | None = None) -> None:
        self.data_path = Path(data_path) if data_path else None

    def status(self) -> str:
        if not self.data_path:
            return "not_configured"
        return "configured" if self.data_path.exists() else "missing"

    def load(self) -> list[GeospatialService]:
        if not self.data_path:
            return []
        if not self.data_path.exists():
            raise FileNotFoundError(f"INDE catalog not found: {self.data_path}")

        suffix = self.data_path.suffix.lower()
        if suffix == ".csv":
            return self._load_csv()
        if suffix == ".json":
            return self._load_json()
        raise ValueError("INDE catalog must be CSV or JSON")

    @staticmethod
    def search_remote(
        text: str,
        endpoint: str = DEFAULT_INDE_CSW_ENDPOINT,
        *,
        client: httpx.Client | None = None,
        max_records: int = 50,
    ) -> list[GeospatialService]:
        """Discover geospatial metadata through the official INDE OGC CSW catalog."""
        query = text.strip()
        parsed = urlparse(endpoint.strip())
        if not query:
            raise ValueError("Informe um termo para pesquisar no catálogo INDE.")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("O endpoint CSW do catálogo INDE precisa ser uma URL HTTP/HTTPS válida.")
        if not 1 <= max_records <= 100:
            raise ValueError("max_records precisa estar entre 1 e 100.")

        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<csw:GetRecords xmlns:csw="http://www.opengis.net/cat/csw/2.0.2" '
            'xmlns:ogc="http://www.opengis.net/ogc" service="CSW" version="2.0.2" '
            'resultType="results" startPosition="1" maxRecords="' + str(max_records) + '" '
            'outputFormat="application/xml" '
            'outputSchema="http://www.opengis.net/cat/csw/2.0.2">'
            '<csw:Query typeNames="csw:Record"><csw:ElementSetName>summary</csw:ElementSetName>'
            '<csw:Constraint version="1.1.0"><ogc:Filter><ogc:PropertyIsLike '
            'wildCard="*" singleChar="?" escapeChar="\\">'
            '<ogc:PropertyName>csw:AnyText</ogc:PropertyName><ogc:Literal>*'
            + query.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            + '*</ogc:Literal></ogc:PropertyIsLike></ogc:Filter>'
            '</csw:Constraint></csw:Query></csw:GetRecords>'
        )
        owned = client is None
        http = client or httpx.Client(timeout=25.0, follow_redirects=True)
        try:
            response = http.post(
                endpoint,
                content=body.encode("utf-8"),
                headers={"Content-Type": "application/xml; charset=utf-8", "Accept": "application/xml"},
            )
            response.raise_for_status()
            root = ET.fromstring(response.content)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Consulta ao catálogo INDE falhou: {exc}") from exc
        except ET.ParseError as exc:
            raise RuntimeError("O catálogo INDE retornou XML inválido.") from exc
        finally:
            if owned:
                http.close()

        def local_text(node: ET.Element, *names: str) -> str | None:
            wanted = {name.casefold() for name in names}
            for child in node.iter():
                local = child.tag.rsplit("}", 1)[-1].casefold()
                if local in wanted and child.text and child.text.strip():
                    return child.text.strip()
            return None

        records: list[GeospatialService] = []
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1].casefold() != "record":
                continue
            title = local_text(node, "title")
            if not title:
                continue
            references: list[tuple[str, str]] = []
            keywords: list[str] = []
            for child in node.iter():
                local = child.tag.rsplit("}", 1)[-1].casefold()
                value = (child.text or "").strip()
                if not value:
                    continue
                if local in {"references", "onlineresource"} and value.startswith(("http://", "https://")):
                    references.append((value, str(child.attrib.get("scheme") or "")))
                elif local in {"subject", "keyword"}:
                    keywords.append(value)
            service_type = None
            for _url, scheme in references:
                upper_scheme = scheme.upper()
                for candidate in ("WFS", "WMS", "WCS", "WMTS", "CSW", "OGC:API"):
                    if candidate in upper_scheme:
                        service_type = candidate
                        break
                if service_type:
                    break
            identifier = local_text(node, "identifier") or title
            records.append(GeospatialService(
                service_id=identifier,
                title=title,
                provider=local_text(node, "creator", "publisher", "contributor"),
                service_type=service_type,
                url=references[0][0] if references else None,
                layer=None,
                keywords=tuple(keywords),
                updated_at=local_text(node, "date", "modified"),
            ))
        return records

    def search(
        self,
        *,
        text: str | None = None,
        state: str | None = None,
        city: str | None = None,
        service_type: str | None = None,
    ) -> list[GeospatialService]:
        services = self.load()
        needle = text.casefold() if text else None
        wanted_state = state.casefold() if state else None
        wanted_city = city.casefold() if city else None
        wanted_type = service_type.casefold() if service_type else None

        result: list[GeospatialService] = []
        for service in services:
            haystack = " ".join(
                (service.title, service.provider or "", service.layer or "", *service.keywords)
            ).casefold()
            if needle and needle not in haystack:
                continue
            if wanted_state and (service.state or "").casefold() != wanted_state:
                continue
            if wanted_city and (service.city or "").casefold() != wanted_city:
                continue
            if wanted_type and (service.service_type or "").casefold() != wanted_type:
                continue
            result.append(service)
        return result

    def _load_csv(self) -> list[GeospatialService]:
        with self.data_path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [self._from_mapping(row) for row in csv.DictReader(handle)]

    def _load_json(self) -> list[GeospatialService]:
        payload = json.loads(self.data_path.read_text(encoding="utf-8"))
        rows: Any = payload.get("services", payload) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise TypeError("INDE JSON catalog must contain a list of services")
        return [self._from_mapping(row) for row in rows]

    @staticmethod
    def _from_mapping(row: dict[str, Any]) -> GeospatialService:
        keywords = row.get("keywords", ())
        if isinstance(keywords, str):
            keywords = tuple(item.strip() for item in keywords.split(",") if item.strip())
        else:
            keywords = tuple(str(item) for item in keywords or ())

        return GeospatialService(
            service_id=str(row.get("service_id") or row.get("id") or ""),
            title=str(row.get("title") or row.get("name") or ""),
            provider=row.get("provider"),
            service_type=row.get("service_type") or row.get("type"),
            url=row.get("url"),
            layer=row.get("layer") or row.get("type_name"),
            keywords=keywords,
            state=row.get("state") or row.get("uf"),
            city=row.get("city") or row.get("municipality"),
            updated_at=row.get("updated_at"),
        )
