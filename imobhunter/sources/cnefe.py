import csv
import gzip
import io
import json
import os
import re
import time
import unicodedata
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from imobhunter.application.address import normalize_request, normalize_text
from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus
from imobhunter.sources.base import SourceAdapter


_FIELD_ALIASES = {
    "street": ("NM_LOGR", "NM_LOGRADOURO", "LOGRADOURO", "NOME_LOGRADOURO"),
    "number": ("NR_ENDERECO", "NUMERO", "NUM", "NUMERO_ENDERECO"),
    "city": ("NM_MUNICIPIO", "MUNICIPIO", "NOME_MUNICIPIO"),
    "state": ("SIGLA_UF", "UF"),
    "latitude": ("LATITUDE", "LAT"),
    "longitude": ("LONGITUDE", "LON", "LONG"),
    "unique_code": ("COD_UNICO", "CODIGO_UNICO", "CD_UNICO"),
    "block": ("QUADRA", "CD_QUADRA"),
    "cep": ("CEP",),
    "modifier": ("DSC_MODIFICADOR", "MODIFICADOR"),
    "species": ("CD_ESPECIE", "ESPECIE", "DSC_ESPECIE"),
    "building_type": ("CD_TIPO_EDIFICACAO", "TIPO_EDIFICACAO", "DSC_TIPO_EDIFICACAO"),
    "geocode_level": ("NV_GEO_COORD", "NIVEL_GEO_COORD"),
    "establishment": ("NM_ESTABELECIMENTO", "NOME_ESTABELECIMENTO"),
    "sector": ("CD_SETOR", "SETOR_CENSITARIO", "CD_SETOR_CENSITARIO"),
    "face": ("FACE",),
    "locality": ("NM_LOCALIDADE", "LOCALIDADE"),
}

CNEFE_FTP_ROOT = (
    "https://ftp.ibge.gov.br/"
    "Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/"
    "Censo_Demografico_2022/Arquivos_CNEFE/CSV/Municipio/"
)
IBGE_MUNICIPALITIES_API = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
USER_AGENT = "ImobHunter-BR/0.1 (official IBGE CNEFE integration)"
MUNICIPALITY_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_CNEFE_DOWNLOAD_BYTES = 512 * 1024 * 1024


def _clean_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return "".join(char for char in value.upper() if char.isalnum() or char == "_")


def _pick(row: dict[str, Any], field: str) -> Any:
    normalized = {_clean_key(key): value for key, value in row.items()}
    for alias in _FIELD_ALIASES[field]:
        value = normalized.get(_clean_key(alias))
        if value not in (None, ""):
            return value
    return None


def _float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _rows_from_json(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("type") == "FeatureCollection":
        for feature in payload.get("features", []):
            properties = dict(feature.get("properties") or {})
            geometry = feature.get("geometry") or {}
            coordinates = geometry.get("coordinates")
            if geometry.get("type") == "Point" and isinstance(coordinates, list) and len(coordinates) >= 2:
                properties.setdefault("LONGITUDE", coordinates[0])
                properties.setdefault("LATITUDE", coordinates[1])
            yield properties
    elif isinstance(payload, list):
        yield from payload
    else:
        raise ValueError("CNEFE JSON must be a FeatureCollection or a list")


def _rows(path: Path) -> Iterable[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in {".json", ".geojson"}:
        return _rows_from_json(path)
    if suffix == ".csv":
        def read_csv() -> Iterable[dict[str, Any]]:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                yield from csv.DictReader(handle, delimiter=";")
        return read_csv()
    if suffix == ".zip":
        def read_zip() -> Iterable[dict[str, Any]]:
            with zipfile.ZipFile(path) as archive:
                csv_names = [
                    name for name in archive.namelist()
                    if not name.endswith("/") and Path(name).suffix.lower() == ".csv"
                ]
                if len(csv_names) != 1:
                    raise ValueError("CNEFE ZIP must contain exactly one CSV file")
                if archive.testzip() is not None:
                    raise ValueError("CNEFE ZIP contains corrupted data")
                with archive.open(csv_names[0], "r") as binary:
                    text = io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
                    yield from csv.DictReader(text, delimiter=";")
        return read_zip()
    raise ValueError("CNEFE file must be CSV, JSON, GeoJSON or ZIP")


def _http_json(url: str) -> Any:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def _http_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, identity"})
    with urlopen(request, timeout=20) as response:
        payload = response.read()
        content_encoding = (response.headers.get("Content-Encoding") or "").lower().strip()
        # Some IBGE directory responses arrive gzip-compressed. Decoding the
        # gzip header directly as UTF-8 raises the reported 0x8b error.
        if content_encoding == "gzip" or payload.startswith(b"\x1f\x8b"):
            payload = gzip.decompress(payload)
        return payload.decode("utf-8-sig", errors="replace")


def _municipality_catalog(cache_dir: Path) -> list[dict[str, Any]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "municipalities.json"
    if cache_path.is_file():
        age = time.time() - cache_path.stat().st_mtime
        if age < MUNICIPALITY_CACHE_TTL_SECONDS:
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(payload, list):
                    return payload
            except (OSError, json.JSONDecodeError):
                pass

    municipalities = _http_json(IBGE_MUNICIPALITIES_API)
    if not isinstance(municipalities, list):
        raise TypeError("IBGE municipality catalog returned an invalid payload")
    temp_path = cache_path.with_suffix(".json.part")
    try:
        temp_path.write_text(
            json.dumps(municipalities, ensure_ascii=False),
            encoding="utf-8",
        )
        temp_path.replace(cache_path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise
    return municipalities


def _municipality_zip_url(city: str, state: str, cache_dir: Path) -> str:
    municipalities = _municipality_catalog(cache_dir)
    wanted_city = normalize_text(city) or ""
    wanted_state = normalize_text(state) or ""
    matches = [
        item for item in municipalities
        if normalize_text(str(item.get("nome") or "")) == wanted_city
        and normalize_text(
            str(item.get("microrregiao", {}).get("mesorregiao", {}).get("UF", {}).get("sigla") or "")
        ) == wanted_state
    ]
    if len(matches) != 1:
        raise ValueError(f"IBGE municipality not uniquely resolved: {city}/{state}")
    code = str(matches[0]["id"])
    uf_dir = f"{code[:2]}_{wanted_state}"
    listing_url = urljoin(CNEFE_FTP_ROOT, f"{uf_dir}/")
    listing = _http_text(listing_url)
    pattern = re.compile(
        r'href=["\']([^"\']*' + re.escape(code) + r'_[^"\']+\.zip)["\']',
        re.IGNORECASE,
    )
    match = pattern.search(listing)
    if not match:
        raise FileNotFoundError(f"Official CNEFE ZIP not found for municipality {code}")
    return urljoin(listing_url, match.group(1))


def _download_remote_zip(url: str, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    filename = url.rsplit("/", 1)[-1]
    target = cache_dir / filename
    if target.is_file() and target.stat().st_size > 0:
        try:
            with zipfile.ZipFile(target) as archive:
                if archive.testzip() is None:
                    return target
        except (OSError, zipfile.BadZipFile):
            target.unlink(missing_ok=True)

    temp = target.with_suffix(target.suffix + ".part")
    request = Request(url, headers={"User-Agent": USER_AGENT})
    downloaded = 0
    try:
        with urlopen(request, timeout=120) as response, temp.open("wb") as handle:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_CNEFE_DOWNLOAD_BYTES:
                raise ValueError("CNEFE download exceeds the configured size limit")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > MAX_CNEFE_DOWNLOAD_BYTES:
                    raise ValueError("CNEFE download exceeds the configured size limit")
                handle.write(chunk)
        with zipfile.ZipFile(temp) as archive:
            if archive.testzip() is not None:
                raise ValueError("Downloaded CNEFE ZIP is corrupted")
        temp.replace(target)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return target



class CNEFEAdapter(SourceAdapter):
    source_id = "ibge_cnefe"
    name = "IBGE / CNEFE"
    category = "address"

    def __init__(self, data_path: str | Path | None = None, cache_dir: str | Path | None = None) -> None:
        configured = data_path or os.getenv("IMOBHUNTER_CNEFE_PATH")
        self.data_path = Path(configured).expanduser() if configured else None
        configured_cache = cache_dir or os.getenv("IMOBHUNTER_CNEFE_CACHE")
        self.cache_dir = (
            Path(configured_cache).expanduser()
            if configured_cache
            else Path.home() / ".imobhunter" / "cache" / "cnefe"
        )

    def status(self) -> SourceStatus:
        if self.data_path is None:
            return SourceStatus(
                self.source_id,
                self.name,
                "available",
                "Integração oficial IBGE habilitada; o arquivo municipal é baixado sob demanda e mantido em cache local.",
            )
        if not self.data_path.is_file():
            return SourceStatus(
                self.source_id,
                self.name,
                "error",
                f"CNEFE file not found: {self.data_path}",
            )
        return SourceStatus(self.source_id, self.name, "available")

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        request.validate()
        status = self.status()
        if status.status != "available":
            raise RuntimeError(status.message or "CNEFE source unavailable")

        normalized = normalize_request(request)
        if not normalized.street_name:
            return []

        wanted_street = normalize_text(normalized.street_name) or ""
        wanted_number = normalize_text(normalized.number)
        max_results = 100
        wanted_city = normalize_text(normalized.city)
        wanted_state = normalize_text(normalized.state)
        if not wanted_city or not wanted_state:
            raise ValueError("CNEFE national lookup requires city and state")

        data_path = self.data_path
        if data_path is None:
            remote_url = _municipality_zip_url(wanted_city, wanted_state, self.cache_dir)
            data_path = _download_remote_zip(remote_url, self.cache_dir)

        records: list[PropertyRecord] = []
        for row in _rows(data_path):
            raw_street = str(_pick(row, "street") or "")
            street = normalize_text(raw_street) or ""
            # CNEFE may store the street type inside NM_LOGR ("R PAMPLONA"),
            # while the search parser separates it ("PAMPLONA"). Compare both
            # representations so valid streets are not discarded.
            parsed_row_street = normalize_text(
                normalize_request(SearchRequest(address=raw_street)).street_name
            ) or street
            number = normalize_text(str(_pick(row, "number") or ""))
            if wanted_street not in {street, parsed_row_street}:
                continue
            if wanted_number and number != wanted_number:
                continue
            row_city = normalize_text(str(_pick(row, "city") or ""))
            row_state = normalize_text(str(_pick(row, "state") or ""))
            if wanted_city and row_city and row_city != wanted_city:
                continue
            if wanted_state and row_state and row_state != wanted_state:
                continue

            attributes = {
                "cep": _pick(row, "cep"),
                "modifier": _pick(row, "modifier"),
                "species": _pick(row, "species"),
                "building_type": _pick(row, "building_type"),
                "geocode_level": _pick(row, "geocode_level"),
                "establishment_name": _pick(row, "establishment"),
                "sector": _pick(row, "sector"),
                "face": _pick(row, "face"),
                "locality": _pick(row, "locality"),
                "source": "CNEFE / IBGE",
                "source_reference": "IBGE CNEFE 2022",
            }
            attributes = {key: value for key, value in attributes.items() if value not in (None, "")}
            unique_code = _pick(row, "unique_code")
            block = _pick(row, "block")
            records.append(
                PropertyRecord(
                    property_id=str(unique_code) if unique_code is not None else None,
                    address=f"{street} {number}".strip(),
                    city=row_city or wanted_city,
                    state=row_state or wanted_state,
                    block=str(block) if block is not None else None,
                    latitude=_float(_pick(row, "latitude")),
                    longitude=_float(_pick(row, "longitude")),
                    attributes=attributes,
                    provenance=(Provenance(self.source_id, confidence=0.90),),
                )
            )
            if len(records) >= max_results:
                break
        return records
