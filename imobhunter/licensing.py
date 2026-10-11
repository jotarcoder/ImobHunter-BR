"""Online license gate for ImobHunter desktop. No admin secret is embedded here."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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

    base = (api_url or os.environ.get("IMOBHUNTER_LICENSE_API") or DEFAULT_LICENSE_API).rstrip("/")
    payload = json.dumps({"user_id": normalized_id, "activation_key": key}).encode()
    request = Request(
        f"{base}/api/license/activate",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=8) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            result = json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            result = {}
        message = str(result.get("error") or "O servidor recusou a ativação sem informar o motivo.")
        code = str(result.get("code") or "SEM_CODIGO")
        raise LicenseError(f"[HTTP {exc.code} · {code}] {message}") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise LicenseError(
            "Não foi possível validar a licença no servidor. Verifique a conexão e tente novamente."
        ) from exc
    if result.get("authorized") is not True:
        code = str(result.get("code") or "SEM_CODIGO")
        message = str(result.get("error") or "O servidor não autorizou a licença e não informou o motivo.")
        raise LicenseError(f"[{code}] {message}")
    return result


class LicenseError(RuntimeError):
    """Raised when the server does not authorize desktop features."""
