from __future__ import annotations
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
import httpx

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")
ADMIN_EMAIL = "juninhoovf@gmail.com"
LICENSE_SIGNING_SECRET = os.getenv("IMOBHUNTER_LICENSE_SIGNING_SECRET", "")

class LicenseConfigError(RuntimeError): pass
@dataclass(frozen=True)
class LicenseSettings:
    url: str
    publishable_key: str
    secret_key: str
    signing_secret: str

def settings() -> LicenseSettings:
    values = (SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, SUPABASE_SECRET_KEY, LICENSE_SIGNING_SECRET)
    if not all(values):
        raise LicenseConfigError("Sistema de licenças não configurado no ambiente.")
    return LicenseSettings(*values)

def hash_license_key(value: str) -> str:
    return hashlib.sha256(value.strip().encode()).hexdigest()

def hash_device_id(value: str) -> str:
    return hashlib.sha256(value.strip().encode()).hexdigest()

def new_license_key() -> str:
    raw = secrets.token_hex(16).upper()
    return "IMH-" + "-".join(raw[i:i+8] for i in range(0, 32, 8))

def _headers(key: str) -> dict[str, str]:
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

def auth_user(access_token: str) -> dict:
    cfg = settings()
    r = httpx.get(f"{cfg.url}/auth/v1/user", headers={"apikey": cfg.publishable_key, "Authorization": f"Bearer {access_token}"}, timeout=10)
    r.raise_for_status()
    return r.json()

def admin_login(email: str, password: str) -> dict:
    cfg = settings()
    if email.lower() != ADMIN_EMAIL: raise PermissionError("Administrador não autorizado.")
    r = httpx.post(f"{cfg.url}/auth/v1/token?grant_type=password", headers={"apikey": cfg.publishable_key, "Content-Type": "application/json"}, json={"email": email, "password": password}, timeout=10)
    if r.status_code >= 400: raise PermissionError("Credenciais inválidas.")
    return r.json()

def list_licenses() -> list[dict]:
    cfg = settings()
    r = httpx.get(f"{cfg.url}/rest/v1/licenses?select=*,license_activations(*)&order=created_at.desc", headers=_headers(cfg.secret_key), timeout=10)
    r.raise_for_status()
    return r.json()

def create_license(*, max_devices: int = 1, expires_at: str | None = None, notes: str | None = None) -> tuple[str, dict]:
    cfg = settings()
    key = new_license_key()
    payload = {"key_hash": hash_license_key(key), "key_last4": key[-4:], "status": "active", "max_devices": max_devices, "expires_at": expires_at, "notes": notes}
    r = httpx.post(f"{cfg.url}/rest/v1/licenses", headers={**_headers(cfg.secret_key), "Prefer": "return=representation"}, json=payload, timeout=10)
    r.raise_for_status()
    return key, r.json()[0]

def set_license_status(license_id: str, status: str) -> dict:
    cfg = settings()
    if status not in {"active", "revoked", "expired"}: raise ValueError("Status inválido.")
    patch = {"status": status, "revoked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) if status == "revoked" else None}
    r = httpx.patch(f"{cfg.url}/rest/v1/licenses?id=eq.{license_id}", headers={**_headers(cfg.secret_key), "Prefer": "return=representation"}, json=patch, timeout=10)
    r.raise_for_status()
    return r.json()[0]

def activate_license(key: str, device_id: str, device_label: str | None = None) -> dict:
    cfg = settings()
    kh = hash_license_key(key)
    r = httpx.get(f"{cfg.url}/rest/v1/licenses?key_hash=eq.{kh}&select=*", headers=_headers(cfg.secret_key), timeout=10)
    r.raise_for_status()
    rows = r.json()
    if not rows: raise PermissionError("Licença não encontrada.")
    lic = rows[0]
    if lic["status"] != "active": raise PermissionError("Licença não está ativa.")
    if lic.get("expires_at") and lic["expires_at"] <= time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()):
        set_license_status(lic["id"], "expired")
        raise PermissionError("Licença expirada.")
    dh = hash_device_id(device_id)
    r = httpx.get(f"{cfg.url}/rest/v1/license_activations?license_id=eq.{lic['id']}&device_hash=eq.{dh}&select=*", headers=_headers(cfg.secret_key), timeout=10)
    r.raise_for_status()
    if r.json():
        row = r.json()[0]
        httpx.patch(f"{cfg.url}/rest/v1/license_activations?id=eq.{row['id']}", headers=_headers(cfg.secret_key), json={"last_seen_at": "now()", "active": True, "device_label": device_label}, timeout=10)
        return {"license_id": lic["id"], "status": "active", "message": "Dispositivo já autorizado."}
    r = httpx.get(f"{cfg.url}/rest/v1/license_activations?license_id=eq.{lic['id']}&active=eq.true&select=id", headers={**_headers(cfg.secret_key), "Prefer": "count=exact"}, timeout=10)
    r.raise_for_status()
    used = int(r.headers.get("content-range", "*/0").rsplit("/", 1)[-1])
    if used >= int(lic["max_devices"]): raise PermissionError("Limite de dispositivos da licença atingido.")
    r = httpx.post(f"{cfg.url}/rest/v1/license_activations", headers=_headers(cfg.secret_key), json={"license_id": lic["id"], "device_hash": dh, "device_label": device_label}, timeout=10)
    r.raise_for_status()
    return {"license_id": lic["id"], "status": "active", "message": "Dispositivo ativado."}

def issue_session_marker(license_id: str, device_id: str, expires_at: int) -> str:
    cfg = settings()
    payload = f"{license_id}.{hash_device_id(device_id)}.{expires_at}".encode()
    sig = hmac.new(cfg.signing_secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"{license_id}.{expires_at}.{sig}"


def verify_session_marker(marker: str, device_id: str) -> str:
    cfg = settings()
    parts = marker.split(".")
    if len(parts) != 3:
        raise PermissionError("Sessão de licença inválida.")
    license_id, expires_raw, signature = parts
    try:
        expires_at = int(expires_raw)
    except ValueError as exc:
        raise PermissionError("Sessão de licença inválida.") from exc
    if expires_at < int(time.time()):
        raise PermissionError("Sessão de licença expirada.")
    payload = f"{license_id}.{hash_device_id(device_id)}.{expires_at}".encode()
    expected = hmac.new(cfg.signing_secret.encode(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise PermissionError("Assinatura da licença inválida.")
    r = httpx.get(
        f"{cfg.url}/rest/v1/license_activations?license_id=eq.{license_id}&device_hash=eq.{hash_device_id(device_id)}&active=eq.true&select=license_id",
        headers=_headers(cfg.secret_key),
        timeout=10,
    )
    r.raise_for_status()
    if not r.json():
        raise PermissionError("Dispositivo não está autorizado.")
    return license_id
