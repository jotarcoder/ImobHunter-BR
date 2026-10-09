from __future__ import annotations

import json
import uuid
from io import BytesIO
from urllib.error import HTTPError
from unittest.mock import patch

import pytest

from imobhunter.licensing import LicenseError, activate, get_user_id


def test_user_id_is_persistent_and_uuid(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("imobhunter.licensing.os.name", "posix")
    first = get_user_id()
    second = get_user_id()
    assert first == second
    assert str(uuid.UUID(first)) == first


def test_activation_sends_user_id_and_hex_key(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"authorized":true,"plan":"annual"}'

    def fake_urlopen(request, timeout):
        assert request.full_url == "https://license.example/api/license/activate"
        assert timeout == 8
        payload = json.loads(request.data)
        assert payload["user_id"] == "00000000-0000-4000-8000-000000000001"
        assert payload["activation_key"] == "A" * 64
        return Response()

    with patch("imobhunter.licensing.urlopen", fake_urlopen):
        result = activate(
            "00000000-0000-4000-8000-000000000001",
            "A" * 64,
            "https://license.example",
        )
    assert result["authorized"] is True


def test_activation_denial_raises_license_error() -> None:
    error = HTTPError(
        "https://license.example/api/license/activate",
        403,
        "Forbidden",
        {},
        BytesIO(b'{"error":"Licen\u00e7a suspensa"}'),
    )
    with patch("imobhunter.licensing.urlopen", side_effect=error):
        with pytest.raises(LicenseError, match="Licença suspensa"):
            activate(
                "00000000-0000-4000-8000-000000000001",
                "A" * 64,
                "https://license.example",
            )
