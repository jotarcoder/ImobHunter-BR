"""Online license gate for ImobHunter desktop. No admin secret is embedded here."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_LICENSE_API = "https://imobhunter-license.workers.dev"
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
        value = str(data.get("user_id", ""))
        if len(value) == 36:
            return value
    except (OSError, ValueError, AttributeError):
        pass
    value = str(uuid.uuid4())
    path.write_text(json.dumps({"user_id": value}), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return value


def activate(user_id: str, activation_key: str, api_url: str | None = None) -> dict:
    base = (api_url or os.environ.get("IMOBHUNTER_LICENSE_API") or DEFAULT_LICENSE_API).rstrip("/")
    payload = json.dumps({"user_id": user_id, "activation_key": activation_key}).encode()
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
        raise LicenseError(str(result.get("error", "Licença não autorizada."))) from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise LicenseError(
            "Não foi possível validar a licença no servidor. Verifique a conexão e tente novamente."
        ) from exc
    if result.get("authorized") is not True:
        raise LicenseError(str(result.get("error", "Licença não autorizada.")))
    return result


class LicenseError(RuntimeError):
    """Raised when the server does not authorize desktop features."""
