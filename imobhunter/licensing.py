""""Online license gate for ImobHunter desktop. No admin secret is embedded here."""
from __future__ import annotations

import json
import os
import ssl
import uuid

import certifi
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__

DEFAULT_LICENSE_API = "https://imobhunter-license.imobhunterbr.workers.dev"
CONTACT_PHONE = "+55 (11) 99903-7737"


def _user_data_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif os.sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = root / "ImobHunter-BR"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_user_id() -> str:
    path = _user_data_dir() / "installation.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = str(data.get("user_id", "")).strip().lower()
        if str(uuid.UUID(value)) == value:
            return value
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    value = str(uuid.uuid4())
    path.write_text(json.dumps({"user_id": value}), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return value


def activate(user_id: str, activation_key: str, api_url: str | None = None) -> dict:
    try:
        normalized_id = str(uuid.UUID(str(user_id).strip())).lower()
    except (ValueError, AttributeError, TypeError) as exc:
        raise LicenseError("O ID desta instalação é inválido. Feche e abra o aplicativo para gerar um ID válido.") from exc

    # Permit formatted clipboard pastes, but only send the exact 64-character hex key.
    key = "".join(str(activation_key).split()).replace("-", "").upper()
    if len(key) != 64 or any(char not in "0123456789ABCDEF" for char in key):
        raise LicenseError("A chave precisa conter 64 caracteres hexadecimais. Copie novamente a chave completa no painel administrativo.")

    # Use the Worker endpoint directly. The Pages proxy adds an unnecessary
    # Cloudflare edge hop that can reject desktop activation before JSON is returned.
    base = (api_url or DEFAULT_LICENSE_API).rstrip("/")
    payload = json.dumps({"user_id": normalized_id, "activation_key": key}).encode()
    request = Request(
        f"{base}/api/license/activate",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"ImobHunter-BR/{__version__} (desktop-license-client)",
        },
        method="POST",
    )
    try:
        with urlopen(
            request,
            timeout=8,
            context=ssl.create_default_context(cafile=certifi.where()),
        ) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        # Preserve non-JSON bodies and Cloudflare request identifiers to distinguish
        # an application-level denial from an upstream security/edge rejection.
        try:
            raw_body = exc.read()
        except OSError:
            raw_body = b""
        body_text = raw_body.decode("utf-8", errors="replace").strip()
        try:
            parsed = json.loads(body_text) if body_text else {}
            result = parsed if isinstance(parsed, dict) else {}
        except ValueError:
            result = {}

        code = str(result.get("code") or "").strip()
        message = str(result.get("error") or "").strip()
        if code or message:
            code = code or "ERRO_SEM_CODIGO"
            message = message or "O servidor recusou a ativação sem informar o motivo."
        else:
            headers = getattr(exc, "headers", None)
            content_type = headers.get("Content-Type", "desconhecido") if headers else "desconhecido"
            ray_id = (headers.get("CF-Ray", "") if headers else "").strip()
            server = (headers.get("Server", "") if headers else "").strip()
            snippet = " ".join(body_text.split())[:180]
            code = "BLOQUEIO_CLOUDFLARE" if ray_id or server.lower() == "cloudflare" else ("RESPOSTA_NAO_JSON" if body_text else "RESPOSTA_VAZIA")
            details = []
            if ray_id:
                details.append(f"CF-Ray: {ray_id}")
            if server:
                details.append(f"Servidor: {server}")
            suffix = f" {'; '.join(details)}." if details else ""
            if snippet:
                message = f"O endpoint de ativação recusou a requisição antes de retornar JSON (Content-Type: {content_type}). Trecho: {snippet}.{suffix}"
            else:
                message = f"O endpoint de ativação retornou HTTP {exc.code} sem corpo JSON (Content-Type: {content_type}).{suffix}"
        raise LicenseError(f"[HTTP {exc.code} · {code}] {message}") from exc
    except URLError as exc:
        reason = exc.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            detail = (
                "A validação do certificado HTTPS falhou. O pacote de certificados "
                "não foi localizado ou não pôde ser validado."
            )
        elif isinstance(reason, ssl.SSLError):
            detail = f"Falha na negociação HTTPS: {str(reason)[:220]}"
        elif isinstance(reason, TimeoutError):
            detail = "A conexão expirou antes de o servidor responder."
        else:
            reason_text = " ".join(str(reason).split())[:220] or type(reason).__name__
            detail = f"Falha de rede antes de receber resposta do servidor: {reason_text}"
        raise LicenseError(f"Não foi possível validar a licença. {detail}") from exc
    except TimeoutError as exc:
        raise LicenseError(
            "A validação da licença expirou após 8 segundos. Verifique a conexão e tente novamente."
        ) from exc
    except ValueError as exc:
        raise LicenseError(
            "O servidor de licenças retornou uma resposta que não é JSON válido."
        ) from exc
    except OSError as exc:
        detail = " ".join(str(exc).split())[:220] or type(exc).__name__
        raise LicenseError(
            f"Falha local de rede ao validar a licença: {detail}"
        ) from exc
    if result.get("authorized") is not True:
        code = str(result.get("code") or "SEM_CODIGO")
        message = str(result.get("error") or "O servidor não autorizou a licença e não informou o motivo.")
        raise LicenseError(f"[{code}] {message}")
    return result


class LicenseError(RuntimeError):
    """Raised when the server does not authorize desktop features."""
