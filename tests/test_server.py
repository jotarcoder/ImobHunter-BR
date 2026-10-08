from fastapi.testclient import TestClient

from imobhunter.server.main import app


def test_healthz() -> None:
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_landing_page_is_served() -> None:
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "ImobHunter-BR" in response.text
    assert "Política de Privacidade" in response.text


def test_removed_landing_script_is_not_served() -> None:
    response = TestClient(app).get("/app.js")
    assert response.status_code == 404
