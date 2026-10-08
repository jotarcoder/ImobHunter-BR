from __future__ import annotations

import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from argon2 import PasswordHasher
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

PH = PasswordHasher()
BEARER = HTTPBearer(auto_error=False)
router = APIRouter()
ADMIN_DIR = Path(__file__).resolve().parent / "admin"


def now() -> datetime:
    return datetime.now(UTC)


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def token() -> str:
    return secrets.token_urlsafe(48)


def public_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(5).upper()}"


def license_key() -> str:
    raw = secrets.token_hex(16).upper()
    return "IMH-LIC-" + "-".join(raw[i:i + 8] for i in range(0, 32, 8))


class Base(DeclarativeBase):
    pass


class Admin(Base):
    __tablename__ = "admins"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30), default="owner")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    licenses: Mapped[list["License"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    devices: Mapped[list["Device"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class License(Base):
    __tablename__ = "licenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(20))
    plan: Mapped[str] = mapped_column(String(40), default="annual")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_devices: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user: Mapped[User] = relationship(back_populates="licenses")
    devices: Mapped[list["Device"]] = relationship(back_populates="license", cascade="all, delete-orphan")


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("license_id", name="uq_device_license"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    license_id: Mapped[int] = mapped_column(ForeignKey("licenses.id"), index=True)
    device_hash: Mapped[str] = mapped_column(String(64), index=True)
    platform: Mapped[str] = mapped_column(String(30))
    app_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user: Mapped[User] = relationship(back_populates="devices")
    license: Mapped[License] = relationship(back_populates="devices")


class SessionToken(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("admins.id"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    license_id: Mapped[int | None] = mapped_column(ForeignKey("licenses.id"), nullable=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str] = mapped_column(String(64))
    event: Mapped[str] = mapped_column(String(80), index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


def engine():
    url = os.getenv("DATABASE_URL", "sqlite:///./imobhunter-admin.db")
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[11:]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[13:]
    args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, connect_args=args)


ENGINE = engine()
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(ENGINE)
    email = os.getenv("IMOBHUNTER_ADMIN_EMAIL")
    password = os.getenv("IMOBHUNTER_ADMIN_PASSWORD")
    if not email or not password:
        return
    with SessionLocal() as db:
        if not db.scalar(select(Admin).where(Admin.email == email.lower().strip())):
            db.add(Admin(email=email.lower().strip(), password_hash=PH.hash(password)))
            db.commit()


def db() -> Session:
    return SessionLocal()


def audit(db: Session, actor_type: str, actor_id: str, event: str, request: Request, details: str = "") -> None:
    db.add(AuditLog(actor_type=actor_type, actor_id=actor_id, event=event,
                    details=details[:2000], ip=request.client.host if request.client else None))


def admin(request: Request, db: Session) -> Admin:
    raw = request.cookies.get("imh_admin_session")
    if not raw:
        raise HTTPException(401, "admin authentication required")
    s = db.scalar(select(SessionToken).where(SessionToken.token_hash == sha(raw), SessionToken.kind == "admin"))
    if not s or s.revoked_at or s.expires_at <= now() or not s.admin_id:
        raise HTTPException(401, "admin session expired")
    obj = db.get(Admin, s.admin_id)
    if not obj or not obj.active:
        raise HTTPException(403, "admin disabled")
    csrf = request.cookies.get("imh_admin_csrf")
    if request.method in {"POST", "PATCH", "PUT", "DELETE"} and not csrf:
        raise HTTPException(403, "csrf validation failed")
    if request.method in {"POST", "PATCH", "PUT", "DELETE"} and not secrets.compare_digest(csrf, request.headers.get("x-csrf-token", "")):
        raise HTTPException(403, "csrf validation failed")
    return obj


def client(credentials: HTTPAuthorizationCredentials | None, db: Session) -> tuple[User, SessionToken]:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "authentication required")
    s = db.scalar(select(SessionToken).where(SessionToken.token_hash == sha(credentials.credentials), SessionToken.kind == "client"))
    if not s or s.revoked_at or s.expires_at <= now() or not s.user_id or not s.license_id or not s.device_id:
        raise HTTPException(401, "session expired")
    obj = db.get(User, s.user_id)
    if not obj or obj.status != "active":
        raise HTTPException(403, "user disabled")
    return obj, s



class Login(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)


class NewUser(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=10, max_length=128)
    notes: str = Field(default="", max_length=2000)


class UserPatch(BaseModel):
    status: str | None = None
    notes: str | None = Field(default=None, max_length=2000)


class NewLicense(BaseModel):
    user_id: int
    days: int = Field(default=365, ge=1, le=3650)
    plan: str = Field(default="annual", min_length=2, max_length=40)


class Extend(BaseModel):
    days: int = Field(ge=1, le=3650)


class Activate(BaseModel):
    user_id: str = Field(min_length=6, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    license_key: str = Field(min_length=20, max_length=80)
    device_id: str = Field(min_length=16, max_length=256)
    platform: str = Field(min_length=2, max_length=30)
    app_version: str = Field(min_length=1, max_length=40)


class Heartbeat(BaseModel):
    device_id: str = Field(min_length=16, max_length=256)
    app_version: str = Field(min_length=1, max_length=40)


def require_admin(request: Request) -> Admin:
    with db() as session:
        obj = admin(request, session)
        session.expunge(obj)
        return obj


@router.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse(ADMIN_DIR / "index.html", media_type="text/html")


@router.get("/admin/app.js", include_in_schema=False)
def admin_js():
    return FileResponse(ADMIN_DIR / "app.js", media_type="text/javascript")


@router.get("/admin/styles.css", include_in_schema=False)
def admin_css():
    return FileResponse(ADMIN_DIR / "styles.css", media_type="text/css")


@router.post("/api/admin/auth/login")
def admin_login(payload: Login, request: Request, response: Response):
    with db() as session:
        obj = session.scalar(select(Admin).where(Admin.email == payload.email.lower().strip()))
        if not obj or not obj.active:
            raise HTTPException(401, "credenciais inválidas")
        try:
            PH.verify(obj.password_hash, payload.password)
        except Exception:
            audit(session, "system", "0", "admin.login_failed", request)
            session.commit()
            raise HTTPException(401, "credenciais inválidas")
        raw, csrf = token(), token()
        session.add(SessionToken(token_hash=sha(raw), kind="admin", admin_id=obj.id, expires_at=now() + timedelta(hours=8)))
        obj.last_login_at = now()
        audit(session, "admin", str(obj.id), "admin.login", request)
        session.commit()
        response.set_cookie("imh_admin_session", raw, httponly=True, secure=True, samesite="strict", max_age=28800)
        response.set_cookie("imh_admin_csrf", csrf, httponly=False, secure=True, samesite="strict", max_age=28800)
        return {"ok": True, "csrf": csrf, "admin": {"email": obj.email, "role": obj.role}}


@router.post("/api/admin/auth/logout")
def admin_logout(request: Request, response: Response):
    raw = request.cookies.get("imh_admin_session")
    with db() as session:
        if raw:
            s = session.scalar(select(SessionToken).where(SessionToken.token_hash == sha(raw), SessionToken.kind == "admin"))
            if s:
                s.revoked_at = now()
                session.commit()
    response.delete_cookie("imh_admin_session")
    response.delete_cookie("imh_admin_csrf")
    return {"ok": True}


@router.get("/api/admin/me")
def admin_me(admin_user: Admin = Depends(require_admin)):
    return {"email": admin_user.email, "role": admin_user.role}


@router.get("/api/admin/dashboard")
def dashboard(admin_user: Admin = Depends(require_admin)):
    with db() as session:
        return {
            "users": session.scalar(select(func.count()).select_from(User)) or 0,
            "active_users": session.scalar(select(func.count()).select_from(User).where(User.status == "active")) or 0,
            "active_licenses": session.scalar(select(func.count()).select_from(License).where(License.status == "active", License.expires_at > now())) or 0,
            "active_devices": session.scalar(select(func.count()).select_from(Device).where(Device.status == "active")) or 0,
            "recent_events": [{"event": x.event, "actor": x.actor_id, "created_at": x.created_at.isoformat(), "details": x.details or ""}
                              for x in session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(12)).all()],
        }


@router.get("/api/admin/users")
def users(admin_user: Admin = Depends(require_admin)):
    with db() as session:
        return [{"id": u.id, "public_id": u.public_id, "name": u.name, "email": u.email, "status": u.status,
                 "created_at": u.created_at.isoformat(), "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None}
                for u in session.scalars(select(User).order_by(User.created_at.desc())).all()]


@router.post("/api/admin/users")
def create_user(payload: NewUser, request: Request, admin_user: Admin = Depends(require_admin)):
    with db() as session:
        email = payload.email.lower().strip()
        if session.scalar(select(User).where(User.email == email)):
            raise HTTPException(409, "e-mail já cadastrado")
        obj = User(public_id=public_id("IMH-U"), name=payload.name.strip(), email=email,
                   password_hash=PH.hash(payload.password), notes=payload.notes)
        session.add(obj)
        session.flush()
        audit(session, "admin", str(admin_user.id), "user.created", request, obj.public_id)
        session.commit()
        return {"id": obj.id, "public_id": obj.public_id, "name": obj.name, "email": obj.email}


@router.patch("/api/admin/users/{user_id}")
def patch_user(user_id: int, payload: UserPatch, request: Request, admin_user: Admin = Depends(require_admin)):
    if payload.status not in {None, "active", "suspended", "blocked"}:
        raise HTTPException(400, "status inválido")
    with db() as session:
        obj = session.get(User, user_id)
        if not obj:
            raise HTTPException(404, "usuário não encontrado")
        if payload.status:
            obj.status = payload.status
        if payload.notes is not None:
            obj.notes = payload.notes
        audit(session, "admin", str(admin_user.id), "user.updated", request, obj.public_id)
        session.commit()
        return {"ok": True}


@router.get("/api/admin/licenses")
def licenses(admin_user: Admin = Depends(require_admin)):
    with db() as session:
        rows = session.scalars(select(License).order_by(License.created_at.desc())).all()
        return [{"id": x.id, "public_id": x.public_id, "user_id": x.user_id, "user": x.user.name,
                 "key_prefix": x.key_prefix, "plan": x.plan, "status": x.status,
                 "starts_at": x.starts_at.isoformat(), "expires_at": x.expires_at.isoformat(), "max_devices": x.max_devices}
                for x in rows]


@router.post("/api/admin/licenses")
def create_license(payload: NewLicense, request: Request, admin_user: Admin = Depends(require_admin)):
    with db() as session:
        user = session.get(User, payload.user_id)
        if not user:
            raise HTTPException(404, "usuário não encontrado")
        raw = license_key()
        obj = License(public_id=public_id("IMH-L"), user_id=user.id, key_hash=sha(raw), key_prefix=raw[:16],
                      plan=payload.plan, starts_at=now(), expires_at=now() + timedelta(days=payload.days),
                      max_devices=1)
        session.add(obj)
        audit(session, "admin", str(admin_user.id), "license.created", request, obj.public_id)
        session.commit()
        return {"license": {"id": obj.id, "public_id": obj.public_id, "expires_at": obj.expires_at.isoformat()}, "key": raw}


@router.post("/api/admin/licenses/{license_id}/revoke")
def revoke_license(license_id: int, request: Request, admin_user: Admin = Depends(require_admin)):
    with db() as session:
        obj = session.get(License, license_id)
        if not obj:
            raise HTTPException(404, "licença não encontrada")
        obj.status, obj.revoked_at = "revoked", now()
        audit(session, "admin", str(admin_user.id), "license.revoked", request, obj.public_id)
        session.commit()
        return {"ok": True}


@router.post("/api/admin/licenses/{license_id}/extend")
def extend_license(license_id: int, payload: Extend, request: Request, admin_user: Admin = Depends(require_admin)):
    with db() as session:
        obj = session.get(License, license_id)
        if not obj:
            raise HTTPException(404, "licença não encontrada")
        obj.expires_at = max(obj.expires_at, now()) + timedelta(days=payload.days)
        obj.status = "active"
        audit(session, "admin", str(admin_user.id), "license.extended", request, f"{obj.public_id}:{payload.days}")
        session.commit()
        return {"ok": True, "expires_at": obj.expires_at.isoformat()}


@router.get("/api/admin/devices")
def devices(admin_user: Admin = Depends(require_admin)):
    with db() as session:
        rows = session.scalars(select(Device).order_by(Device.last_seen_at.desc())).all()
        return [{"id": x.id, "user": x.user.name, "user_id": x.user.public_id, "platform": x.platform,
                 "app_version": x.app_version, "status": x.status, "first_seen_at": x.first_seen_at.isoformat(),
                 "last_seen_at": x.last_seen_at.isoformat(), "last_ip": x.last_ip} for x in rows]


@router.post("/api/admin/devices/{device_id}/revoke")
def revoke_device(device_id: int, request: Request, admin_user: Admin = Depends(require_admin)):
    with db() as session:
        obj = session.get(Device, device_id)
        if not obj:
            raise HTTPException(404, "dispositivo não encontrado")
        obj.status = "revoked"
        audit(session, "admin", str(admin_user.id), "device.revoked", request, str(device_id))
        session.commit()
        return {"ok": True}


@router.get("/api/admin/audit")
def audit_list(admin_user: Admin = Depends(require_admin)):
    with db() as session:
        rows = session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)).all()
        return [{"event": x.event, "actor_type": x.actor_type, "actor_id": x.actor_id, "details": x.details or "",
                 "ip": x.ip or "", "created_at": x.created_at.isoformat()} for x in rows]


@router.post("/api/v1/activate")
def activate(payload: Activate, request: Request):
    with db() as session:
        user = session.scalar(select(User).where(User.public_id == payload.user_id))
        if not user or user.status != "active":
            raise HTTPException(401, "credenciais inválidas")
        try:
            PH.verify(user.password_hash, payload.password)
        except Exception:
            audit(session, "user", user.public_id, "client.login_failed", request)
            session.commit()
            raise HTTPException(401, "credenciais inválidas")
        license_hash = sha(payload.license_key.strip().upper())
        lic = session.scalar(select(License).where(License.user_id == user.id, License.key_hash == license_hash))
        if not lic or lic.status != "active" or not (lic.starts_at <= now() < lic.expires_at):
            if lic and lic.expires_at <= now() and lic.status == "active":
                lic.status = "expired"
            audit(session, "user", user.public_id, "license.activation_denied", request)
            session.commit()
            raise HTTPException(403, "licença inválida ou expirada")
        device_hash = sha(payload.device_id)
        device = session.scalar(select(Device).where(Device.license_id == lic.id))
        if device and device.device_hash != device_hash and device.status == "active":
            raise HTTPException(409, "esta licença já está vinculada a outro dispositivo")
        if device and device.status == "revoked":
            raise HTTPException(403, "dispositivo revogado")
        if not device:
            device = Device(user_id=user.id, license_id=lic.id, device_hash=device_hash,
                            platform=payload.platform, app_version=payload.app_version)
            session.add(device)
            session.flush()
        device.status, device.platform, device.app_version, device.last_seen_at = "active", payload.platform, payload.app_version, now()
        device.last_ip = request.client.host if request.client else None
        user.last_login_at = now()
        access = token()
        expires = now() + timedelta(hours=12)
        session.add(SessionToken(token_hash=sha(access), kind="client", user_id=user.id,
                                 license_id=lic.id, device_id=device.id, expires_at=expires))
        audit(session, "user", user.public_id, "client.activated", request, f"{payload.platform}:{payload.app_version}")
        session.commit()
        return {"access_token": access, "expires_at": expires.isoformat(), "user_id": user.public_id,
                "name": user.name, "license_expires_at": lic.expires_at.isoformat(), "max_devices": lic.max_devices}


@router.post("/api/v1/heartbeat")
def heartbeat(payload: Heartbeat, credentials: HTTPAuthorizationCredentials | None = Depends(BEARER), request: Request = None):
    with db() as session:
        user, client_session = client(credentials, session)
        lic = session.get(License, client_session.license_id)
        if not lic or lic.user_id != user.id or lic.status != "active" or not (lic.starts_at <= now() < lic.expires_at):
            raise HTTPException(403, "licença expirada ou revogada")
        device = session.scalar(select(Device).where(Device.id == client_session.device_id,
                                                       Device.user_id == user.id,
                                                       Device.license_id == lic.id,
                                                       Device.device_hash == sha(payload.device_id),
                                                       Device.status == "active"))
        if not device:
            raise HTTPException(403, "dispositivo não autorizado")
        device.app_version, device.last_seen_at = payload.app_version, now()
        session.commit()
        return {"ok": True, "license_expires_at": lic.expires_at.isoformat()}
