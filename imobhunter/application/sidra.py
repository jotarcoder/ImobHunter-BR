from __future__ import annotations

from typing import Any

import httpx

SIDRA_BASE_URL = "https://apisidra.ibge.gov.br/values"
POPULATION_VARIABLE = "9324"  # Estimativas da população residente


def fetch_population_estimate(municipality_code: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    """Fetch the latest available resident-population estimate from IBGE SIDRA table 6579.

    municipality_code is the 7-digit IBGE municipality code. The query runs only
    on demand and returns source metadata together with the original SIDRA row.
    """
    code = "".join(ch for ch in str(municipality_code) if ch.isdigit())
    if len(code) != 7:
        raise ValueError("Informe o código IBGE do município com 7 dígitos.")
    url = f"{SIDRA_BASE_URL}/t/6579/n6/{code}/v/{POPULATION_VARIABLE}/p/last%201"
    owned = client is None
    http = client or httpx.Client(
        timeout=httpx.Timeout(20.0),
        headers={"User-Agent": "ImobHunter-BR/0.1 (desktop market intelligence)", "Accept": "application/json"},
        follow_redirects=True,
    )
    try:
        response = http.get(url)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("Não foi possível consultar o IBGE/SIDRA agora. Verifique a conexão e tente novamente.") from exc
    finally:
        if owned:
            http.close()
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], dict):
        raise RuntimeError("O SIDRA não retornou uma estimativa populacional para esse município.")
    row = payload[1]
    return {
        "source": "IBGE — SIDRA, tabela 6579",
        "source_url": "https://sidra.ibge.gov.br/tabela/6579",
        "api_url": url,
        "municipality_code": code,
        "municipality": row.get("Município") or row.get("Município (Código)") or code,
        "period": row.get("Ano") or row.get("Período") or "mais recente disponível",
        "population": row.get("Valor"),
        "raw": row,
    }
