"""Import large São Paulo fiscal-cadastre Parquet files into indexed local SQLite.

The import is bounded in memory, atomic, offline, and does not require access
to taxpayer/debt portals. Input may be an independently redistributed dataset:
provenance is the actual selected local file, not an invented government claim.
"""
from __future__ import annotations

from pathlib import Path
import os
import re
import sqlite3
import unicodedata
import uuid
from collections.abc import Callable


def _key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", text.upper()).split())


def street_key(value: object) -> str:
    text = _key(value)
    first, separator, rest = text.partition(" ")
    aliases = {"R": "RUA", "AV": "AVENIDA", "PCA": "PRACA", "PC": "PRACA"}
    return aliases.get(first, first) + (separator + rest if separator else "")


def number_key(value: object) -> str:
    text = _key(value)
    # The official 'NUMERO DO IMOVEL' column may contain numeric text.
    return text.lstrip("0") or ("0" if text else "")


def _columns(names: list[str]) -> dict[str, str | None]:
    available = {_key(name): name for name in names}

    def pick(*keys: str) -> str | None:
        return next((available[_key(name)] for name in keys if _key(name) in available), None)

    columns = {
        "sql": pick("SQL", "NUMERO DO CONTRIBUINTE"),
        "street": pick("NOME DE LOGRADOURO DO IMOVEL", "LOGRADOURO"),
        "number": pick("NUMERO DO IMOVEL", "NUMERO"),
        "complement": pick("COMPLEMENTO DO IMOVEL"),
        "neighborhood": pick("BAIRRO DO IMOVEL"),
        "zip_code": pick("CEP DO IMOVEL", "CEP"),
        "year": pick("ANO DO EXERCICIO"),
        "area": pick("AREA DO TERRENO"),
        "built_area": pick("AREA CONSTRUIDA"),
    }
    if not all(columns[k] for k in ("sql", "street", "number")):
        raise ValueError(
            "Parquet sem as colunas obrigatórias de São Paulo: SQL/NUMERO DO CONTRIBUINTE, "
            "logradouro e número do imóvel."
        )
    return columns


def _value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()[:500]


def _area(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(str(value).replace(",", "."))
        if not 0 <= number <= 1_000_000_000:
            return None
        return number
    except (ValueError, TypeError):
        return None


def import_sp_iptu_parquet(
    source: str | Path,
    target: str | Path | None = None,
    *,
    progress: Callable[[int], None] | None = None,
) -> tuple[Path, int]:
    """Import selected fields in Arrow record batches; never load 3.8M rows at once.

    Existing SQLite is atomically replaced only after successful indexing.
    The original Parquet file is never modified or deleted.
    """
    path = Path(source)
    if not path.is_file() or path.suffix.lower() != ".parquet":
        raise ValueError("Selecione um arquivo Parquet (.parquet) válido.")
    with path.open("rb") as f:
        if f.read(4) != b"PAR1":
            raise ValueError("Arquivo não é um Parquet válido.")
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "O leitor Parquet (pyarrow) não está disponível nesta instalação. "
            "Instale uma versão do ImobHunter com suporte a Parquet."
        ) from exc

    parquet = pq.ParquetFile(path)
    columns = _columns(parquet.schema.names)
    if parquet.metadata.num_rows > 20_000_000:
        raise ValueError("Arquivo excede o limite de 20 milhões de registros.")
    dest = Path(target) if target else Path.home() / ".imobhunter" / "sp_iptu" / "iptu_sp.sqlite3"
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(f".{dest.stem}-{uuid.uuid4().hex}.tmp")
    count = 0
    names = list(dict.fromkeys(x for x in columns.values() if x))
    try:
        with sqlite3.connect(temporary) as db:
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("""CREATE TABLE iptu_sp (
                sql TEXT NOT NULL, sql_digits TEXT NOT NULL,
                street TEXT NOT NULL, street_key TEXT NOT NULL,
                number TEXT NOT NULL, number_key TEXT NOT NULL,
                complement TEXT, neighborhood TEXT, zip_code TEXT,
                sector TEXT, block TEXT, lot TEXT,
                area_m2 REAL, built_area_m2 REAL, exercise_year TEXT
            )""")
            db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
            insert = """INSERT INTO iptu_sp (
                sql,sql_digits,street,street_key,number,number_key,complement,
                neighborhood,zip_code,sector,block,lot,area_m2,built_area_m2,exercise_year
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
            for batch in parquet.iter_batches(batch_size=5000, columns=names):
                data = batch.to_pydict()
                buffer = []
                for i in range(batch.num_rows):
                    def get(key: str):
                        name = columns[key]
                        return data[name][i] if name else None
                    sql = _value(get("sql"))
                    street = _value(get("street"))
                    number = _value(get("number"))
                    if not sql or not street or not number:
                        continue
                    digits = "".join(c for c in sql if c.isdigit())
                    sector = digits[:3] if len(digits) >= 10 else ""
                    block = digits[3:6] if len(digits) >= 10 else ""
                    lot = digits[6:10] if len(digits) >= 10 else ""
                    buffer.append((
                        sql, digits, street, street_key(street), number,
                        number_key(number), _value(get("complement")),
                        _value(get("neighborhood")), _value(get("zip_code")),
                        sector, block, lot, _area(get("area")),
                        _area(get("built_area")), _value(get("year")),
                    ))
                db.executemany(insert, buffer)
                count += len(buffer)
                if progress:
                    progress(count)
            if not count:
                raise ValueError("Parquet sem registros com SQL, logradouro e número.")
            db.execute("CREATE INDEX idx_iptu_sp_address ON iptu_sp(street_key,number_key)")
            db.execute("CREATE INDEX idx_iptu_sp_lot ON iptu_sp(block,lot)")
            db.execute("CREATE INDEX idx_iptu_sp_sql ON iptu_sp(sql_digits)")
            db.executemany(
                "INSERT INTO metadata(key,value) VALUES (?,?)",
                [("source_file", path.name), ("record_count", str(count)), ("location", "São Paulo/SP")],
            )
            check = db.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise RuntimeError("Falha na verificação de integridade SQLite.")
        os.replace(temporary, dest)
    finally:
        temporary.unlink(missing_ok=True)
    return dest, count


def search_sp_iptu_sqlite(database_path: str | Path, request) -> list[dict]:
    """Parameterized indexed lookups, restricted to São Paulo capital."""
    if request.state and _key(request.state) not in ("SP", "SAO PAULO"):
        return []
    if request.city and _key(request.city) not in ("SAO PAULO",):
        return []
    # An address alone is ambiguous for multi-million-row data; require number.
    if request.address and request.number:
        address = street_key(request.address)
        num = number_key(request.number)
        sql_query = "SELECT * FROM iptu_sp WHERE street_key=? AND number_key=? LIMIT 200"
        args = (address, num)
    elif request.block and request.lot:
        sql_query = "SELECT * FROM iptu_sp WHERE block=? AND lot=? LIMIT 200"
        args = (str(request.block).strip().zfill(3), str(request.lot).strip().zfill(4))
    else:
        return []
    uri = f"file:{Path(database_path).resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(sql_query, args).fetchall()
    return [{
        "sql": r["sql"], "endereco": r["street"], "numero": r["number"],
        "complemento": r["complement"], "bairro": r["neighborhood"],
        "cep": r["zip_code"], "municipio": "São Paulo", "uf": "SP",
        "setor": r["sector"], "quadra": r["block"], "lote": r["lot"],
        "area_m2": r["area_m2"], "area_construida_m2": r["built_area_m2"],
        "ano_base": r["exercise_year"], "official_source": "Arquivo local: IPTU SP (Parquet)",
    } for r in rows]
