"""Offline verification of short, signed *identities* valid until the paid expiry.

The server alone holds the P-256 private key. The desktop has only the public key.
Being unable to reach Cloudflare is not the same as an explicit license denial.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import time
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from .licensing import LicenseDenied, LicenseError, _user_data_dir, activate

# Public, non-secret verification key corresponding to LICENSE_SIGNING_PRIVATE_JWK on the Worker.
# Never put the private JWK in the repository or an installer.
PUBLIC_KEY_HEX = (
    "04d671f1297a1943ceb146d64c6ab328f709a1a7ac7ab3a5102570a7ea6b62ff"
    "71619b7dc10634a1e7fa01f5f09135dd9bdac78b6a97f21c9c4c0e1a9fd83d2afb"
)
_CLOCK_TOLERANCE_SECONDS = 300
_MAX_CERTIFICATE_SIZE = 8192


def _path() -> Path:
    return _user_data_dir() / "license_certificate.json"


def _key_fingerprint(key: str) -> str:
    normalized = "".join(str(key).split()).replace("-", "").upper()
    return hashlib.sha256(normalized.encode("ascii")).hexdigest().upper()


def _base64url(value: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise LicenseError("Certificado de licença com codificação inválida.")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _read_saved() -> dict:
    try:
        path = _path()
        if path.stat().st_size > _MAX_CERTIFICATE_SIZE:
            raise LicenseError("Certificado salvo excede o tamanho permitido.")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("invalid certificate envelope")
        return data
    except (FileNotFoundError, OSError, ValueError, TypeError) as exc:
        raise LicenseError("Nenhum certificado offline válido foi encontrado neste dispositivo.") from exc


def _write_saved(data: dict) -> None:
    path = _path()
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(path)


def verify_certificate(certificate: dict, user_id: str, activation_key: str, *,
                       now: int | None = None, last_seen: int = 0) -> dict:
    """Verify signature, device/key binding, expiration and obvious clock rollback."""
    if not isinstance(certificate, dict) or certificate.get("v") != 1:
        raise LicenseError("Formato do certificado de licença inválido.")
    payload64 = certificate.get("payload")
    signature64 = certificate.get("signature")
    try:
        payload_bytes = _base64url(payload64)
        signature = _base64url(signature64)
        if len(payload_bytes) > 2048 or len(signature) != 64:
            raise ValueError("unexpected certificate size")
        public_key = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), bytes.fromhex(PUBLIC_KEY_HEX)
        )
        r = int.from_bytes(signature[:32], "big")
        s = int.from_bytes(signature[32:], "big")
        public_key.verify(
            encode_dss_signature(r, s), payload64.encode("ascii"), ec.ECDSA(hashes.SHA256())
        )
        claims = json.loads(payload_bytes)
    except (InvalidSignature, LicenseError, binascii.Error, ValueError, TypeError, UnicodeError) as exc:
        raise LicenseError("Assinatura digital do certificado de licença inválida.") from exc
    if not isinstance(claims, dict):
        raise LicenseError("Dados do certificado de licença inválidos.")
    if (
        type(claims.get("v")) is not int or claims["v"] != 1
        or claims.get("user_id") != str(user_id).strip().lower()
        or claims.get("key_sha256") != _key_fingerprint(activation_key)
        or claims.get("plan") not in ("monthly", "annual")
        or type(claims.get("issued_at")) is not int
        or type(claims.get("expires_at")) is not int
        or claims["issued_at"] < 0
        or claims["expires_at"] <= claims["issued_at"]
    ):
        raise LicenseError("Certificado não pertence a esta instalação e chave de licença.")
    current = int(time.time()) if now is None else int(now)
    if current + _CLOCK_TOLERANCE_SECONDS < last_seen:
        raise LicenseError("O relógio do computador retrocedeu. Reconecte para verificar a licença.")
    if current + _CLOCK_TOLERANCE_SECONDS < claims["issued_at"]:
        raise LicenseError("O relógio do computador está incorreto. Corrija a data e hora.")
    if current >= claims["expires_at"]:
        raise LicenseError("A licença venceu. Reconecte à internet para renovar a autorização.")
    return claims



def cached_authorization(user_id: str, activation_key: str, *, now: int | None = None) -> dict:
    """Allow offline execution only with a signed, still-valid prior authorization."""
    saved = _read_saved()
    if saved.get("blocked") is True:
        raise LicenseError("Licença bloqueada pelo servidor. Reconecte para validar.")
    seen = saved.get("last_seen", 0)
    if type(seen) is not int or seen < 0:
        raise LicenseError("Histórico de data de verificação inválido.")
    current = int(time.time()) if now is None else int(now)
    claims = verify_certificate(
        saved.get("certificate"), user_id, activation_key, now=current, last_seen=seen
    )
    # Remember the greatest local time observed; prevent accidental clock rollback.
    if current > seen:
        _write_saved({**saved, "last_seen": current})
    return {"authorized": True, "mode": "offline", "expires_at": claims["expires_at"],
            "plan": claims["plan"], "user_id": claims["user_id"]}


def _save_authorized_certificate(certificate: dict, user_id: str, activation_key: str) -> dict:
    current = int(time.time())
    claims = verify_certificate(certificate, user_id, activation_key, now=current)
    # Only an authenticated online success unblocks a previously denied license.
    _write_saved({"certificate": certificate, "blocked": False,
                  "last_seen": max(current, claims["issued_at"])})
    return claims


def _mark_denied() -> None:
    """Persist explicit server denial; never mistake transport failures for a revocation."""
    try:
        saved = _read_saved()
        _write_saved({**saved, "blocked": True})
    except (LicenseError, OSError):
        # No cached certificate exists or the storage device is unavailable.
        pass


def check_license(user_id: str, activation_key: str) -> dict:
    """Online first; fall back to signed proof only for transport/service failure."""
    try:
        result = activate(user_id, activation_key)
    except LicenseDenied:
        _mark_denied()
        raise
    except LicenseError as network_error:
        try:
            return cached_authorization(user_id, activation_key)
        except LicenseError as offline_error:
            raise LicenseError(
                f"Sem conexão com o servidor e sem autorização offline válida: {offline_error}. "
                f"Falha de comunicação: {network_error}"
            ) from network_error

    certificate = result.get("license_certificate")
    if not isinstance(certificate, dict):
        raise LicenseError(
            "O servidor autorizou a chave, mas não enviou o certificado assinado. "
            "Aguarde a configuração do serviço de licenças."
        )
    claims = _save_authorized_certificate(certificate, user_id, activation_key)
    return {**result, "mode": "online", "expires_at": claims["expires_at"]}
