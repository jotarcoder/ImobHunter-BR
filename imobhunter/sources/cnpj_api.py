from __future__ import annotations

import os
import time
from typing import Any

import httpx


TOKEN_URL = "https://apigateway.conectagov.estaleiro.serpro.gov.br/oauth2/jwt-token"
DEFAULT_ENDPOINTS = {
    "basica": "https://apigateway.conectagov.estaleiro.serpro.gov.br/api-cnpj-basica/v2/basica",
    "empresa": "https://apigateway.conectagov.estaleiro.serpro.gov.br/api-cnpj-empresa/v2/empresa",
    "qsa": "https://apigateway.conectagov.estaleiro.serpro.gov.br/api-cnpj-qsa/v2/qsa",
}
TIMEOUT_SECONDS = 8.0


class CNPJApiClient:
    """Optional authenticated Conecta gov.br CNPJ enrichment for known CNPJs.

    This client enriches CNPJs already discovered by the local/open establishment
    index. It is not a geographic discovery API. Credentials are read from the
    environment and must never be embedded in a desktop installer.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        cpf_usuario: str,
        *,
        token_url: str = TOKEN_URL,
        endpoints: dict[str, str] | None = None,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.cpf_usuario = cpf_usuario.strip()
        self.token_url = token_url.rstrip("/")
        self.endpoints = {
            key: (endpoints or {}).get(key, value).rstrip("/")
            for key, value in DEFAULT_ENDPOINTS.items()
        }
        self.timeout = timeout
        self._access_token: str | None = None
        self._token_expires_at = 0.0

    @classmethod
    def from_environment(cls) -> CNPJApiClient | None:
        client_id = os.getenv("IMOBHUNTER_CNPJ_API_CLIENT_ID", "").strip()
        client_secret = os.getenv("IMOBHUNTER_CNPJ_API_CLIENT_SECRET", "").strip()
        cpf_usuario = os.getenv("IMOBHUNTER_CNPJ_API_CPF_USUARIO", "").strip()
        if not (client_id and client_secret and cpf_usuario):
            return None
        return cls(client_id, client_secret, cpf_usuario)

    def _token(self) -> str:
        now = time.monotonic()
        if self._access_token and now < self._token_expires_at - 30:
            return self._access_token

        response = httpx.post(
            self.token_url,
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
            headers={"Accept": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise RuntimeError("Conecta gov.br não retornou access_token")
        self._access_token = str(payload["access_token"])
        try:
            expires_in = max(60, int(payload.get("expires_in", 300)))
        except (TypeError, ValueError):
            expires_in = 300
        self._token_expires_at = now + expires_in
        return self._access_token

    @staticmethod
    def _digits(cnpj: str) -> str:
        return "".join(char for char in str(cnpj) if char.isdigit())

    def lookup(self, cnpj: str) -> dict[str, Any]:
        digits = self._digits(cnpj)
        if len(digits) != 14:
            raise ValueError("A consulta Conecta gov.br exige CNPJ com 14 dígitos")

        token = self._token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "x-cpf-usuario": self.cpf_usuario,
        }
        result: dict[str, Any] = {}
        for service, base_url in self.endpoints.items():
            response = httpx.get(
                f"{base_url}/{digits}",
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError(f"Resposta inválida da API CNPJ ({service})")
            result[service] = payload
        return result
