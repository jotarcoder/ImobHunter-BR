import os
from datetime import UTC, datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///./test-imobhunter-admin.db"

from fastapi.testclient import TestClient

from imobhunter.server.admin import Base, ENGINE, SessionLocal, User, License, sha
from imobhunter.server.main import app

Base.metadata.drop_all(ENGINE)
Base.metadata.create_all(ENGINE)


def _seed() -> tuple[User, str]:
    from argon2 import PasswordHasher
    from imobhunter.server.admin import license_key, public_id

    ph = PasswordHasher()
    key = license_key()
    with SessionLocal() as db:
        user = User(public_id=public_id("IMH-U"), name="Teste", email="teste@example.com", password_hash=ph.hash("senha-segura-123"))
        db.add(user)
        db.flush()
        db.add(License(public_id=public_id("IMH-L"), user_id=user.id, key_hash=sha(key), key_prefix=key[:16],
                       starts_at=datetime.now(UTC), expires_at=datetime.now(UTC)+timedelta(days=365),
                       max_devices=1, plan="annual"))
        db.commit()
        return user, key


def test_activation_and_device_limit():
    user, key = _seed()
    client = TestClient(app)
    payload={"user_id":user.public_id,"password":"senha-segura-123","license_key":key,"device_id":"device-1234567890123456","platform":"windows","app_version":"0.1.3"}
    r=client.post("/api/v1/activate",json=payload)
    assert r.status_code==200
    r2=client.post("/api/v1/activate",json={**payload,"device_id":"device-abcdefghijklmnop"})
    assert r2.status_code==409


def test_expired_license_is_rejected():
    user, key = _seed()
    with SessionLocal() as db:
        lic=db.query(License).filter(License.user_id==user.id).first()
        lic.expires_at=datetime.now(UTC)-timedelta(seconds=1)
        db.commit()
    client=TestClient(app)
    r=client.post("/api/v1/activate",json={"user_id":user.public_id,"password":"senha-segura-123","license_key":key,"device_id":"device-expired-123456","platform":"linux","app_version":"0.1.3"})
    assert r.status_code==403
