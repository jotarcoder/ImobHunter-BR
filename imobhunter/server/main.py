from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
import secrets
import time
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from .licenses import ADMIN_EMAIL, activate_license, admin_login, auth_user, create_license, issue_session_marker, list_licenses, set_license_status, verify_session_marker

WEB_DIR = Path(__file__).resolve().parents[2] / "web"

app = FastAPI(
    title="ImobHunter-BR Backend",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="web-assets")
app.mount("/admin", StaticFiles(directory=WEB_DIR / "admin", html=True), name="admin")

_ADMIN_SESSIONS: dict[str, str] = {}

class AdminLogin(BaseModel):
    email: str
    password: str

class LicenseCreate(BaseModel):
    max_devices: int = 1
    expires_at: str | None = None
    notes: str | None = None

class LicenseStatus(BaseModel):
    status: str

class LicenseActivation(BaseModel):
    key: str
    device_id: str
    device_label: str | None = None

class LicenseVerification(BaseModel):
    marker: str
    device_id: str

def _admin_token(request: Request) -> str:
    session = request.cookies.get("imobhunter_admin")
    if not session or session not in _ADMIN_SESSIONS:
        raise HTTPException(status_code=401, detail="Sessão administrativa ausente.")
    try:
        user = auth_user(_ADMIN_SESSIONS[session])
    except Exception as exc:
        _ADMIN_SESSIONS.pop(session, None)
        raise HTTPException(status_code=401, detail="Sessão administrativa expirada.") from exc
    if str(user.get("email", "")).lower() != ADMIN_EMAIL:
        _ADMIN_SESSIONS.pop(session, None)
        raise HTTPException(status_code=403, detail="Administrador não autorizado.")
    return session


@app.get("/", include_in_schema=False)
def landing_page() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html", media_type="text/html")


@app.get("/styles.css", include_in_schema=False)
def landing_styles() -> FileResponse:
    return FileResponse(WEB_DIR / "styles.css", media_type="text/css")


@app.get("/healthz", tags=["system"])
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "imobhunter-backend"}


@app.get("/api", tags=["system"])
def api_root() -> dict[str, str]:
    return {"service": "ImobHunter-BR Backend", "status": "ok"}


@app.post("/api/admin/login", tags=["admin"])
def admin_login_route(payload: AdminLogin, response: Response) -> dict[str, str]:
    try:
        auth = admin_login(payload.email, payload.password)
        user = auth_user(auth["access_token"])
        if str(user.get("email", "")).lower() != ADMIN_EMAIL:
            raise PermissionError("Administrador não autorizado.")
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    session_id = secrets.token_urlsafe(32)
    _ADMIN_SESSIONS[session_id] = auth["access_token"]
    response.set_cookie("imobhunter_admin", session_id, httponly=True, secure=True, samesite="lax", max_age=3600)
    return {"status": "ok"}

@app.post("/api/admin/logout", tags=["admin"])
def admin_logout(request: Request, response: Response) -> dict[str, str]:
    session = request.cookies.get("imobhunter_admin")
    if session:
        _ADMIN_SESSIONS.pop(session, None)
    response.delete_cookie("imobhunter_admin")
    return {"status": "ok"}

@app.get("/api/admin/licenses", tags=["admin"])
def admin_list(request: Request) -> dict:
    _admin_token(request)
    try:
        return {"licenses": list_licenses()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Banco de licenças indisponível.") from exc

@app.post("/api/admin/licenses", tags=["admin"])
def admin_create(request: Request, payload: LicenseCreate) -> dict:
    _admin_token(request)
    if not 1 <= payload.max_devices <= 25:
        raise HTTPException(status_code=422, detail="max_devices deve estar entre 1 e 25.")
    try:
        key, row = create_license(max_devices=payload.max_devices, expires_at=payload.expires_at, notes=payload.notes)
        return {"key": key, "license": row}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Não foi possível criar a licença.") from exc

@app.patch("/api/admin/licenses/{license_id}", tags=["admin"])
def admin_update(request: Request, license_id: str, payload: LicenseStatus) -> dict:
    _admin_token(request)
    try:
        return set_license_status(license_id, payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Não foi possível alterar a licença.") from exc

@app.post("/api/license/activate", tags=["license"])
def license_activate(payload: LicenseActivation) -> dict:
    try:
        result = activate_license(payload.key, payload.device_id, payload.device_label)
        expires_at = int(time.time()) + 7 * 24 * 3600
        result["marker"] = issue_session_marker(result["license_id"], payload.device_id, expires_at)
        result["expires_at"] = expires_at
        return result
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Serviço de licenças indisponível.") from exc

@app.post("/api/license/verify", tags=["license"])
def license_verify(payload: LicenseVerification) -> dict[str, str]:
    try:
        license_id = verify_session_marker(payload.marker, payload.device_id)
        return {"status": "active", "license_id": license_id}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Serviço de licenças indisponível.") from exc
