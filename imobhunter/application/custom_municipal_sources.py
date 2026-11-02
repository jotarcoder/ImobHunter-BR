"""Per-user municipal sources and authorized local municipal file imports.

The catalogue is private to the desktop machine. No data is uploaded to a
municipal portal, GitHub, Cloudflare, or the ImobHunter licensing service.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, replace
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
from threading import RLock
from urllib.parse import urlsplit
import uuid
from typing import Any

from imobhunter.domain.identity import canonical_text

ALLOWED_FILES = {".csv", ".xlsx", ".json", ".geojson"}
ALLOWED_PROTOCOLS = {"wfs", "arcgis", "website"}
MAX_FILE_BYTES = 80 * 1024 * 1024
MAX_ROWS = 50_000
MAX_SOURCES = 100


def safe_public_url(value: str) -> bool:
    """Reject unsafe/intranet targets and credential-bearing URLs.

    External sites must use HTTPS and a public DNS name; redirects are disabled
    by callers. This is not a grant of municipal API access.
    """
    if not value or len(value) > 2048:
        return False
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower().rstrip(".")
        if url.scheme != "https" or not host or url.username or url.password:
            return False
        if url.port not in (None, 443):
            return False
    except ValueError:
        return False
    if (
        url.fragment or host == "localhost" or host.endswith((".localhost", ".local", ".internal"))
        or not re.fullmatch(r"[a-z0-9.-]+", host) or "." not in host
        or any(part == "" for part in host.split("."))
    ):
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return True
    return False  # Never request raw IPs, including loopback and private ranges.


def infer_protocol(url: str) -> str:
    path = urlsplit(url).path.lower()
    if re.search(r"/(?:feature|map)server/\d+/?$", path):
        return "arcgis"
    if "geoserver" in path or "wfs" in path or "service=wfs" in url.lower():
        return "wfs"
    return "website"


@dataclass(frozen=True)
class CustomMunicipalSource:
    id: str
    city: str
    state: str
    name: str
    url: str = ""
    kind: str = "website"
    file_name: str = ""

    @property
    def source_id(self) -> str:
        return f"local_municipal_{self.id}"

    def matches(self, city: str | None, state: str | None) -> bool:
        # Requiring both prevents a generic query from leaking one municipality's
        # registered source into an identically named city in a different state.
        return bool(city and state and canonical_text(city) == canonical_text(self.city)
                    and canonical_text(state) == canonical_text(self.state))


def _validated(source: CustomMunicipalSource) -> CustomMunicipalSource:
    if not re.fullmatch(r"[0-9a-f]{32}", source.id):
        raise ValueError("Identificador de fonte municipal inválido.")
    if not 1 <= len(source.name.strip()) <= 100:
        raise ValueError("Informe um nome de fonte de até 100 caracteres.")
    if not 2 <= len(source.city.strip()) <= 100:
        raise ValueError("Informe o nome do município.")
    if not re.fullmatch(r"[A-Za-z]{2}", source.state.strip()):
        raise ValueError("Informe uma UF válida de duas letras.")
    if source.kind not in ALLOWED_PROTOCOLS:
        raise ValueError("Tipo de fonte inválido (WFS, ArcGIS ou site).")
    if source.url and not safe_public_url(source.url):
        raise ValueError("Informe um endereço HTTPS público (sem IP privado ou credenciais).")
    if source.kind != "website" and not source.url:
        raise ValueError("Uma API WFS ou ArcGIS precisa de um endpoint HTTPS.")
    if source.kind == "arcgis" and not re.search(
        r"/(?:Feature|Map)Server/\d+/?$", urlsplit(source.url).path, re.IGNORECASE
    ):
        raise ValueError("Informe a URL ArcGIS da camada, terminada em /FeatureServer/0 ou /MapServer/0.")
    if source.file_name and not re.fullmatch(r"[0-9a-f]{32}\.(?:csv|xlsx|json|geojson)", source.file_name):
        raise ValueError("Nome de arquivo cadastral inválido.")
    return replace(source, city=source.city.strip(), state=source.state.strip().upper(),
                   name=source.name.strip(), url=source.url.strip())


def _csv_rows(path: Path) -> list[dict[str, Any]]:
    try:
        data = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        data = path.read_text(encoding="cp1252")
    sample = data[:8192]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(data.splitlines(), delimiter=delimiter)
    if not reader.fieldnames or len(reader.fieldnames) > 256:
        raise ValueError("CSV sem cabeçalho ou com campos demais.")
    rows = []
    for row in reader:
        if len(rows) >= MAX_ROWS:
            raise ValueError("Arquivo excede o limite de 50 mil registros.")
        rows.append({str(key): value for key, value in row.items() if key})
    return rows


def _json_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict):
        if payload.get("type") == "FeatureCollection":
            payload = payload.get("features")
        else:
            payload = payload.get("data", payload.get("items", payload.get("records")))
    if not isinstance(payload, list):
        raise TypeError("JSON precisa conter lista, data/items/records ou GeoJSON FeatureCollection.")
    if len(payload) > MAX_ROWS:
        raise ValueError("Arquivo excede o limite de 50 mil registros.")
    return [row for row in payload if isinstance(row, dict)]


def _xlsx_rows(path: Path) -> list[dict[str, Any]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise ValueError("Para Excel é necessário o componente openpyxl.") from exc
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = book.active
        lines = sheet.iter_rows(values_only=True)
        headers = next(lines, None)
        if not headers or len(headers) > 256:
            raise ValueError("Planilha sem cabeçalho ou com campos demais.")
        keys = [str(h).strip() if h is not None else "" for h in headers]
        rows = []
        for values in lines:
            if len(rows) >= MAX_ROWS:
                raise ValueError("Planilha excede o limite de 50 mil registros.")
            if any(v is not None for v in values):
                rows.append({
                    key: value for key, value in zip(keys, values) if key
                })
        return rows
    finally:
        book.close()


def read_municipal_file(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.suffix.lower() not in ALLOWED_FILES:
        raise ValueError("Selecione CSV, XLSX, JSON ou GeoJSON válido.")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Arquivo maior que 80 MB; divida a exportação municipal.")
    if path.suffix.lower() == ".csv":
        rows = _csv_rows(path)
    elif path.suffix.lower() == ".xlsx":
        rows = _xlsx_rows(path)
    else:
        rows = _json_rows(path)
    if not rows:
        raise ValueError("Nenhuma linha cadastral utilizável foi encontrada.")
    return rows


class CustomMunicipalStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory or (Path.home() / ".imobhunter" / "municipal_sources"))
        self.config_path = self.directory / "sources.json"
        self._lock = RLock()

    def list(self) -> tuple[CustomMunicipalSource, ...]:
        with self._lock:
            if not self.config_path.is_file():
                return ()
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
                raise TypeError("Catálogo de fontes municipais inválido.")
            items = tuple(_validated(CustomMunicipalSource(**row)) for row in payload["sources"])
            if len(items) > MAX_SOURCES or len({x.id for x in items}) != len(items):
                raise ValueError("Catálogo de fontes municipais inconsistente.")
            return items

    def _save(self, items: tuple[CustomMunicipalSource, ...]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.directory / f".sources-{uuid.uuid4().hex}.tmp"
        try:
            tmp.write_text(json.dumps({
                "version": 1, "sources": [asdict(item) for item in items],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.config_path)
        finally:
            tmp.unlink(missing_ok=True)

    def add(self, name: str, city: str, state: str,
            url: str = "", kind: str | None = None) -> CustomMunicipalSource:
        with self._lock:
            items = self.list()
            if len(items) >= MAX_SOURCES:
                raise ValueError("Limite de 100 fontes municipais atingido.")
            record = _validated(CustomMunicipalSource(
                id=uuid.uuid4().hex, name=name, city=city, state=state,
                url=url, kind=kind or infer_protocol(url),
            ))
            self._save((*items, record))
            return record

    def get(self, source_id: str) -> CustomMunicipalSource | None:
        return next((item for item in self.list() if item.source_id == source_id), None)

    def local_path(self, item: CustomMunicipalSource) -> Path | None:
        if not item.file_name:
            return None
        return self.directory / "data" / item.file_name

    def import_file(self, source_id: str, original: Path) -> tuple[CustomMunicipalSource, int]:
        with self._lock:
            items = self.list()
            current = next((item for item in items if item.source_id == source_id), None)
            if current is None:
                raise ValueError("Cadastre o município antes de importar arquivos.")
            original = Path(original)
            rows = read_municipal_file(original)  # Validate before copying.
            path = self.directory / "data" / f"{current.id}{original.suffix.lower()}"
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.parent / f".{uuid.uuid4().hex}.part"
            try:
                with original.open("rb") as source, temporary.open("wb") as target:
                    shutil.copyfileobj(source, target)
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            updated = replace(current, file_name=path.name)
            self._save(tuple(updated if entry.id == current.id else entry for entry in items))
            if current.file_name and current.file_name != path.name:
                (path.parent / current.file_name).unlink(missing_ok=True)
            return updated, len(rows)

    def remove(self, source_id: str) -> bool:
        with self._lock:
            items = self.list()
            current = next((item for item in items if item.source_id == source_id), None)
            if current is None:
                return False
            self._save(tuple(entry for entry in items if entry.id != current.id))
            path = self.local_path(current)
            if path is not None:
                path.unlink(missing_ok=True)
            return True
