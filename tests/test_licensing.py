from __future__ import annotations

import json
import uuid
from io import BytesIO
from urllib.error import HTTPError
from unittest.mock import patch

import pytest

from imobhunter.licensing import DEFAULT_LICENSE_API, LicenseError, activate, get_user_id


def test_default_activation_uses_direct_worker_endpoint() -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"authorized":true,"plan":"annual"}'

    def fake_urlopen(request, timeout):
        assert request.full_url == f"{DEFAULT_LICENSE_API}/api/license/activate"
        assert "workers.dev" in request.full_url
        assert "pages.dev" not in request.full_url
        return Response()

    with patch("imobhunter.licensing.urlopen", fake_urlopen):
        result = activate("00000000-0000-4000-8000-000000000001", "A" * 64)
    assert result["authorized"] is True


def test_user_id_is_persistent_and_uuid(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("imobhunter.licensing.os.name", "posix")
    first = get_user_id()
    second = get_user_id()
    assert first == second
    assert str(uuid.UUID(first)) == first


def test_invalid_persisted_user_id_is_replaced(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("imobhunter.licensing.os.name", "posix")
    data_dir = tmp_path / "ImobHunter-BR"
    data_dir.mkdir()
    (data_dir / "installation.json").write_text('{"user_id":"xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"}', encoding="utf-8")
    generated = get_user_id()
    assert str(uuid.UUID(generated)) == generated
    assert generated != "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"


def test_activation_sends_normalized_user_id_and_hex_key() -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"authorized":true,"plan":"annual"}'

    def fake_urlopen(request, timeout):
        assert request.full_url == "https://license.example/api/license/activate"
        assert request.get_method() == "POST"
        assert request.get_header("Content-type") == "application/json"
        assert timeout == 8
        assert json.loads(request.data) == {
            "user_id": "00000000-0000-4000-8000-000000000001",
            "activation_key": "A" * 64,
        }
        return Response()

    formatted_key = "-".join(["A" * 16] * 4)
    with patch("imobhunter.licensing.urlopen", fake_urlopen):
        result = activate("00000000-0000-4000-8000-000000000001", f"  {formatted_key}\n", "https://license.example/")
    assert result["authorized"] is True


def test_activation_rejects_malformed_key_before_network_call() -> None:
    with (
        patch("imobhunter.licensing.urlopen") as network,
        pytest.raises(LicenseError, match="64 caracteres hexadecimais"),
    ):
        activate("00000000-0000-4000-8000-000000000001", "not-a-key")
    network.assert_not_called()


def test_activation_rejects_invalid_user_id_before_network_call() -> None:
    with (
        patch("imobhunter.licensing.urlopen") as network,
        pytest.raises(LicenseError, match="ID desta instalação é inválido"),
    ):
        activate("not-a-uuid", "A" * 64)
    network.assert_not_called()


def test_activation_denial_includes_worker_code_and_message() -> None:
    error = HTTPError(
        "https://license.example/api/license/activate", 403, "Forbidden", {},
        BytesIO(b'{"code":"ACTIVATION_KEY_MISMATCH","error":"Chave incorreta"}'),
    )
    with (
        patch("imobhunter.licensing.urlopen", side_effect=error),
        pytest.raises(LicenseError, match=r"HTTP 403.*ACTIVATION_KEY_MISMATCH.*Chave incorreta"),
    ):
        activate("00000000-0000-4000-8000-000000000001", "A" * 64, "https://license.example")


def test_activation_rejects_success_http_without_authorized_true() -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"ok":true,"authorized":false,"code":"LICENSE_NOT_ACTIVE","error":"Licenca suspensa"}'

    with (
        patch("imobhunter.licensing.urlopen", return_value=Response()),
        pytest.raises(LicenseError, match=r"LICENSE_NOT_ACTIVE.*Licenca suspensa"),
    ):
        activate("00000000-0000-4000-8000-000000000001", "A" * 64, "https://license.example")


def test_activation_converts_network_errors_to_license_error() -> None:
    with (
        patch("imobhunter.licensing.urlopen", side_effect=TimeoutError("timed out")),
        pytest.raises(LicenseError, match="Não foi possível validar a licença"),
    ):
        activate("00000000-0000-4000-8000-000000000001", "A" * 64)


def test_activation_denial_exposes_non_json_proxy_response() -> None:
    error = HTTPError(
        "https://license.example/api/license/activate",
        403,
        "Forbidden",
        {"Content-Type": "text/html; charset=UTF-8"},
        BytesIO(b"<html><title>Access denied</title><body>Request blocked</body></html>"),
    )
    with (
        patch("imobhunter.licensing.urlopen", side_effect=error),
        pytest.raises(
            LicenseError,
            match=r"HTTP 403.*RESPOSTA_NAO_JSON.*Content-Type: text/html.*Access denied",
        ),
    ):
        activate("00000000-0000-4000-8000-000000000001", "A" * 64, "https://license.example")
