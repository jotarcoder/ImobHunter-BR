from __future__ import annotations

from typing import Any

import httpx

SIDRA_BASE_URL = "https://apisidra.ibge.gov.br/values"
IBGE_LOCALITIES_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
POPULATION_VARIABLE = "9324"
USER_AGENT = "ImobHunter-BR/0.1 (desktop market intelligence)"


def _client_or_create(client: httpx.Client | None) -> tuple[httpx.Client, bool]:
    if client is not None:
        return client, False
    return httpx.Client(
        timeout=httpx.Timeout(20.0),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    ), True


def search_municipalities(query: str, *, client: httpx.Client | None = None) -> list[dict[str, str]]:
    """Search Brazilian municipalities by name through the public IBGE Localities API."""
    term = str(query or "").strip()
    if len(term) < 2:
        raise ValueError("Digite pelo menos duas letras do município.")
    if len(term) > 100:
        raise ValueError("O nome do município é muito longo.")
    http, owned = _client_or_create(client)
    try:
        response = http.get(IBGE_LOCALITIES_URL, params={"nome": term})
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("Não foi possível consultar os municípios do IBGE agora. Verifique a conexão e tente novamente.") from exc
    finally:
        if owned:
            http.close()
    if not isinstance(payload, list):
        raise TypeError("A API de localidades do IBGE retornou uma resposta inválida.")
    matches: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict) or not str(item.get("id", "")).isdigit():
            continue
        region = item.get("microrregiao") or {}
        mesoregion = region.get("mesorregiao") or {}
        state = mesoregion.get("UF") or {}
        name = str(item.get("nome") or "").strip()
        code = str(item.get("id") or "").strip()
        uf = str(state.get("sigla") or "").strip()
        if name and len(code) == 7:
            matches.append({"code": code, "name": name, "state": uf})
    return sorted(matches, key=lambda item: (item["name"].casefold(), item["state"]))


def fetch_population_estimate(
    municipality_code: str, *, client: httpx.Client | None = None
) -> dict[str, Any]:
    """Fetch the latest available resident-population estimate from IBGE SIDRA table 6579.

    Accepts a seven-digit IBGE municipality code. Results include the official source,
    municipality name, reference year, population and original SIDRA response row.
    """
    code = str(municipality_code or "").strip()
    if not code.isdigit() or len(code) != 7:
        raise ValueError("Informe o código IBGE do município com 7 dígitos.")
    url = f"{SIDRA_BASE_URL}/t/6579/n6/{code}/v/{POPULATION_VARIABLE}/p/last%201"
    http, owned = _client_or_create(client)
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
    # The values endpoint normally returns compact keys (MN, D1N, V); accept
    # descriptive aliases too so a change in response presentation fails safely.
    municipality = row.get("Município") or row.get("MN") or row.get("D2N") or code
    period = row.get("Ano") or row.get("Período") or row.get("D1N") or "mais recente disponível"
    population = row.get("Valor") or row.get("V")
    if not population or not str(population).strip().isdigit():
        raise RuntimeError("O SIDRA retornou um valor populacional ausente ou inválido.")
    return {
        "source": "IBGE — SIDRA, tabela 6579",
        "source_url": "https://sidra.ibge.gov.br/tabela/6579",
        "api_url": url,
        "municipality_code": code,
        "municipality": municipality,
        "period": period,
        "population": int(population),
        "raw": row,
    }
