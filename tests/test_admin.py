import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite:///./test-imobhunter-admin.db"

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from imobhunter.server.admin import Base, ENGINE, License, SessionLocal, User, license_key, public_id, sha
from imobhunter.server.main import app


Base.metadata.drop_all(ENGINE)
Base.metadata.create_all(ENGINE)


def _seed() -> tuple[User, str]:
    from argon2 import PasswordHasher

    ph = PasswordHasher()
    key = license_key()
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        user = User(
            public_id=public_id("IMH-U"),
            name="Teste",
            email=f"teste-{suffix}@example.com",
            password_hash=ph.hash("senha-segura-123"),
        )
        db.add(user)
        db.flush()
        db.add(
            License(
                public_id=public_id("IMH-L"),
                user_id=user.id,
                key_hash=sha(key),
                key_prefix=key[:16],
                starts_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=365),
                plan="annual",
            )
        )
        db.commit()
        return user, key


def _activate(client: TestClient, user: User, key: str, device_id: str):
    return client.post(
        "/api/v1/activate",
        json={
            "user_id": user.public_id,
            "password": "senha-segura-123",
            "license_key": key,
            "device_id": device_id,
            "platform": "windows",
            "app_version": "0.1.3",
        },
    )


def test_activation_allows_only_one_device_per_license():
    user, key = _seed()
    client = TestClient(app)

    first = _activate(client, user, key, "device-1234567890123456")
    assert first.status_code == 200

    same_device = _activate(client, user, key, "device-1234567890123456")
    assert same_device.status_code == 200
    token = same_device.json()["access_token"]
    heartbeat = client.post(
        "/api/v1/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={"device_id": "device-1234567890123456", "app_version": "0.1.3"},
    )
    assert heartbeat.status_code == 200
    assert "license_expires_at" in heartbeat.json()
    wrong_device_heartbeat = client.post(
        "/api/v1/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={"device_id": "device-wrong-1234567", "app_version": "0.1.3"},
    )
    assert wrong_device_heartbeat.status_code == 403

    second_device = _activate(client, user, key, "device-abcdefghijklmnop")
    assert second_device.status_code == 409



def test_different_licenses_can_bind_different_devices():
    user, key_one = _seed()
    key_two = license_key()
    with SessionLocal() as db:
        db.add(
            License(
                public_id=public_id("IMH-L"),
                user_id=user.id,
                key_hash=sha(key_two),
                key_prefix=key_two[:16],
                starts_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=365),
                max_devices=1,
                plan="annual",
            )
        )
        db.commit()

    client = TestClient(app)
    assert _activate(client, user, key_one, "device-first-123456").status_code == 200
    assert _activate(client, user, key_two, "device-second-123456").status_code == 200


def test_expired_license_is_rejected():
    user, key = _seed()
    with SessionLocal() as db:
        lic = db.query(License).filter(License.user_id == user.id).first()
        lic.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    client = TestClient(app)
    response = _activate(client, user, key, "device-expired-123456")
    assert response.status_code == 403


def test_legacy_schema_migration_adds_license_columns(tmp_path) -> None:
    from sqlalchemy import create_engine
    from imobhunter.server.admin import _migrate_legacy_schema

    legacy = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with legacy.begin() as connection:
        connection.execute(text("CREATE TABLE devices (id INTEGER PRIMARY KEY, user_id INTEGER)"))
        connection.execute(text("CREATE TABLE sessions (id INTEGER PRIMARY KEY, token_hash VARCHAR(64))"))

    _migrate_legacy_schema(legacy)
    assert "license_id" in {c["name"] for c in inspect(legacy).get_columns("devices")}
    session_columns = {c["name"] for c in inspect(legacy).get_columns("sessions")}
    assert {"license_id", "device_id"} <= session_columns
