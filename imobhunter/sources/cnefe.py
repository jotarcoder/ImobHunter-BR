import csv
import io
import json
import os
import unicodedata
import zipfile
from pathlib import Path
from collections.abc import Iterable
from typing import Any

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
    "building_type": (
        "CD_TIPO_EDIFICACAO",
        "TIPO_EDIFICACAO",
        "DSC_TIPO_EDIFICACAO",
    ),
    "geocode_level": ("NV_GEO_COORD", "NIVEL_GEO_COORD"),
    "establishment": ("NM_ESTABELECIMENTO", "NOME_ESTABELECIMENTO"),
    "sector": ("CD_SETOR", "SETOR_CENSITARIO", "CD_SETOR_CENSITARIO"),
    "face": ("FACE",),
    "locality": ("NM_LOCALIDADE", "LOCALIDADE"),
}


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
            if (
                geometry.get("type") == "Point"
                and isinstance(coordinates, list)
                and len(coordinates) >= 2
            ):
                properties.setdefault("LONGITUDE", coordinates[0])
                properties.setdefault("LATITUDE", coordinates[1])
            yield properties
    elif isinstance(payload, list):
        yield from payload
    else:
        raise ValueError("CNEFE JSON must be a FeatureCollection or a list")


def _rows(path: Path) -> Iterable[dict[str, Any]]:
    if path.suffix.lower() in {".json", ".geojson"}:
        return _rows_from_json(path)
    if path.suffix.lower() == ".csv":
        def read_csv() -> Iterable[dict[str, Any]]:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                yield from csv.DictReader(handle, delimiter=";")

        return read_csv()
    if path.suffix.lower() == ".zip":
        def read_zip() -> Iterable[dict[str, Any]]:
            with zipfile.ZipFile(path) as archive:
                csv_names = [
                    name for name in archive.namelist()
                    if not name.endswith("/") and Path(name).suffix.lower() == ".csv"
                ]
                if not csv_names:
                    raise ValueError("CNEFE ZIP does not contain a CSV file")
                with archive.open(csv_names[0], "r") as binary:
                    text = io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
                    yield from csv.DictReader(text, delimiter=";")

        return read_zip()
    raise ValueError("CNEFE file must be CSV, JSON, GeoJSON or ZIP")


\n\nfrom urllib.parse import urljoin\nfrom urllib.request import Request, urlopen\nimport re\n\n\nCNEFE_FTP_ROOT = (\n    "https://ftp.ibge.gov.br/"\n    "Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/"\n    "Censo_Demografico_2022/Arquivos_CNEFE/CSV/Municipio/"\n)\nIBGE_MUNICIPALITIES_API = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"\n\n\ndef _http_json(url: str) -> Any:\n    request = Request(url, headers={"User-Agent": "ImobHunter-BR/0.1 (CNEFE official source)"})\n    with urlopen(request, timeout=20) as response:\n        return json.load(response)\n\n\ndef _http_text(url: str) -> str:\n    request = Request(url, headers={"User-Agent": "ImobHunter-BR/0.1 (CNEFE official source)"})\n    with urlopen(request, timeout=20) as response:\n        return response.read().decode("utf-8", errors="replace")\n\n\ndef _municipality_zip_url(city: str, state: str) -> str:\n    municipalities = _http_json(IBGE_MUNICIPALITIES_API)\n    wanted_city = normalize_text(city) or ""\n    wanted_state = normalize_text(state) or ""\n    matches = [\n        item for item in municipalities\n        if normalize_text(str(item.get("nome") or "")) == wanted_city\n        and normalize_text(str(item.get("microrregiao", {}).get("mesorregiao", {}).get("UF", {}).get("sigla") or "")) == wanted_state\n    ]\n    if len(matches) != 1:\n        raise ValueError(f"IBGE municipality not uniquely resolved: {city}/{state}")\n    code = str(matches[0]["id"])\n    uf_dir = f"{code[:2]}_{wanted_state}"\n    listing_url = urljoin(CNEFE_FTP_ROOT, f"{uf_dir}/")\n    listing = _http_text(listing_url)\n    pattern = re.compile(r'href=["\\\']([^"\\\']*' + re.escape(code) + r'_[^"\\\']+\\.zip)["\\\']', re.I)\n    match = pattern.search(listing)\n    if not match:\n        raise FileNotFoundError(f"Official CNEFE ZIP not found for municipality {code}")\n    return urljoin(listing_url, match.group(1))\n\n\ndef _download_remote_zip(url: str, cache_dir: Path) -> Path:\n    cache_dir.mkdir(parents=True, exist_ok=True)\n    filename = url.rsplit("/", 1)[-1]\n    target = cache_dir / filename\n    if target.is_file() and target.stat().st_size > 0:\n        return target\n    temp = target.with_suffix(target.suffix + ".part")\n    request = Request(url, headers={"User-Agent": "ImobHunter-BR/0.1 (CNEFE official source)"})\n    try:\n        with urlopen(request, timeout=60) as response, temp.open("wb") as handle:\n            while True:\n                chunk = response.read(1024 * 1024)\n                if not chunk:\n                    break\n                handle.write(chunk)\n        temp.replace(target)\n    except Exception:\n        temp.unlink(missing_ok=True)\n        raise\n    return target\nclass CNEFEAdapter(SourceAdapter):
    source_id = "ibge_cnefe"
    name = "IBGE / CNEFE"
    category = "address"

    def __init__(self, data_path: str | Path | None = None) -> None:
        configured = data_path or os.getenv("IMOBHUNTER_CNEFE_PATH")
        self.data_path = Path(configured).expanduser() if configured else None

    def status(self) -> SourceStatus:
        if self.data_path is None:
            return SourceStatus(
                self.source_id,
                self.name,
                "not_configured",
                "Configure IMOBHUNTER_CNEFE_PATH with an official CNEFE CSV, GeoJSON or ZIP file.",
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
        if not normalized.street_name or not normalized.number:
            return []

        wanted_street = normalize_text(normalized.street_name) or ""
        wanted_number = normalize_text(normalized.number) or ""
        wanted_city = normalize_text(normalized.city)
        wanted_state = normalize_text(normalized.state)
        records: list[PropertyRecord] = []

        for row in _rows(self.data_path):  # type: ignore[arg-type]
            street = normalize_text(str(_pick(row, "street") or "")) or ""
            number = normalize_text(str(_pick(row, "number") or "")) or ""
            if street != wanted_street or number != wanted_number:
                continue

            row_city = normalize_text(str(_pick(row, "city") or ""))
            row_state = normalize_text(str(_pick(row, "state") or ""))
            if wanted_city and row_city and row_city != wanted_city:
                continue
            if wanted_state and row_state and row_state != wanted_state:
                continue

            unique_code = _pick(row, "unique_code")
            block = _pick(row, "block")
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
            }
            attributes = {
                key: value
                for key, value in attributes.items()
                if value not in (None, "")
            }

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
        return records
