from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__

WEB_DIR = Path(__file__).resolve().parents[2] / "web"

app = FastAPI(
    title="ImobHunter-BR Backend",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="web-assets")


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
