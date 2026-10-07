from pathlib import Path

from fastapi.testclient import TestClient

from imobhunter.server.main import app


ROOT = Path(__file__).resolve().parents[1]


def test_landing_page_is_public_and_has_no_search_form() -> None:
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "ImobHunter-BR" in response.text
    assert "CENTRAL DE DOWNLOADS" in response.text
    assert "<form" not in response.text.lower()


def test_landing_assets_are_served() -> None:
    css = TestClient(app).get("/styles.css")
    hero = TestClient(app).get("/assets/hero.svg")

    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]
    assert hero.status_code == 200
    assert "svg" in hero.headers["content-type"]


def test_landing_source_files_exist() -> None:
    assert (ROOT / "web" / "index.html").is_file()
    assert (ROOT / "web" / "styles.css").is_file()
    assert (ROOT / "web" / "assets" / "hero.svg").is_file()
