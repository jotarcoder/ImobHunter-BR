from __future__ import annotations

import base64
import hashlib
import json
import time
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from imobhunter import offline_license as offline
from imobhunter.licensing import LicenseDenied, LicenseError

USER_ID = "00000000-0000-4000-8000-000000000001"
KEY = "A" * 64


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


@pytest.fixture
def signer(monkeypatch, tmp_path):
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_numbers()
    monkeypatch.setattr(offline, "PUBLIC_KEY_HEX",
                        "04" + public.x.to_bytes(32, "big").hex()
                        + public.y.to_bytes(32, "big").hex())
    monkeypatch.setattr(offline, "_path", lambda: tmp_path / "license_certificate.json")

    def issue(*, user_id=USER_ID, key=KEY, expiry=None, iat=None):
        now = int(time.time())
        claims = {
            "v": 1, "user_id": user_id, "plan": "annual",
            "key_sha256": hashlib.sha256(key.encode()).hexdigest().upper(),
            "issued_at": now - 60 if iat is None else iat,
            "expires_at": now + 3600 if expiry is None else expiry,
        }
        encoded = b64(json.dumps(claims, separators=(",", ":")).encode())
        der = private.sign(encoded.encode("ascii"), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        return {"v": 1, "payload": encoded,
                "signature": b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))}

    return issue


def test_signed_license_stays_valid_offline_until_paid_expiry(signer):
    cert = signer()
    offline._save_authorized_certificate(cert, USER_ID, KEY)
    with patch.object(offline, "activate", side_effect=LicenseError("timeout")):
        result = offline.check_license(USER_ID, KEY)
    assert result["authorized"] is True
    assert result["mode"] == "offline"


def test_expired_license_never_authorizes_offline(signer):
    now = int(time.time())
    cert = signer(expiry=now + 10)
    offline._save_authorized_certificate(cert, USER_ID, KEY)
    with pytest.raises(LicenseError, match="venceu"):
        offline.cached_authorization(USER_ID, KEY, now=now + 11)


def test_forged_signature_is_rejected(signer):
    cert = signer()
    signature = bytearray(offline._base64url(cert["signature"]))
    signature[5] ^= 1
    cert["signature"] = b64(signature)
    with pytest.raises(LicenseError, match="Assinatura"):
        offline.verify_certificate(cert, USER_ID, KEY)


def test_device_and_activation_key_are_bound_to_certificate(signer):
    cert = signer()
    with pytest.raises(LicenseError, match="não pertence"):
        offline.verify_certificate(cert, "00000000-0000-4000-8000-000000000002", KEY)
    with pytest.raises(LicenseError, match="não pertence"):
        offline.verify_certificate(cert, USER_ID, "B" * 64)


def test_clock_rollback_blocks_until_online(signer):
    cert = signer()
    now = int(time.time())
    with pytest.raises(LicenseError, match="retrocedeu"):
        offline.verify_certificate(cert, USER_ID, KEY, now=now - 3600, last_seen=now)


def test_confirmed_denial_blocks_offline_but_preserves_certificate(signer):
    cert = signer()
    offline._save_authorized_certificate(cert, USER_ID, KEY)
    with patch.object(offline, "activate", side_effect=LicenseDenied("LICENSE_NOT_ACTIVE")):
        with pytest.raises(LicenseDenied):
            offline.check_license(USER_ID, KEY)
    assert offline._read_saved()["blocked"] is True
    with pytest.raises(LicenseError, match="bloqueada"):
        offline.cached_authorization(USER_ID, KEY)
    assert offline._read_saved()["certificate"] == cert


def test_successful_online_validation_clears_block(signer):
    cert = signer()
    offline._save_authorized_certificate(cert, USER_ID, KEY)
    offline._mark_denied()
    with patch.object(offline, "activate", return_value={
        "authorized": True, "license_certificate": cert
    }):
        result = offline.check_license(USER_ID, KEY)
    assert result["mode"] == "online"
    assert offline._read_saved()["blocked"] is False


def test_first_activation_requires_real_signed_certificate(signer):
    with patch.object(offline, "activate", return_value={"authorized": True}):
        with pytest.raises(LicenseError, match="não enviou o certificado"):
            offline.check_license(USER_ID, KEY)
    with pytest.raises(LicenseError, match="Nenhum certificado"):
        offline.cached_authorization(USER_ID, KEY)


def test_timeout_without_prior_certificate_denies_access_but_not_key(signer):
    with patch.object(offline, "activate", side_effect=LicenseError("timeout")):
        with pytest.raises(LicenseError, match="Sem conexão"):
            offline.check_license(USER_ID, KEY)
    assert not offline._path().exists()


def test_bad_certificate_payload_is_rejected(signer):
    cert = signer()
    cert["payload"] = "not!base64"
    with pytest.raises(LicenseError, match="Assinatura"):
        offline.verify_certificate(cert, USER_ID, KEY)
