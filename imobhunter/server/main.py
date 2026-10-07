from fastapi import FastAPI

from .. import __version__

app = FastAPI(
    title="ImobHunter-BR Backend",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.get("/healthz", tags=["system"])
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "imobhunter-backend"}


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {"service": "ImobHunter-BR Backend", "status": "ok"}
