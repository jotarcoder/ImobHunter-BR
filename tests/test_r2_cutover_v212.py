"""The published landing uses immutable versioned R2 links; no alias-copy release job."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_no_automatic_mutating_cutover_after_pages_deployment():
    # Copying >100 MB R2 objects as aliases failed with InvalidPart.
    # The site already links to immutable versioned files, so avoid any
    # background multipart copy or deletion of previously released files.
    assert not (ROOT / ".github/workflows/r2-v2.1.2-cutover.yml").exists()


def test_versioned_downloads_need_no_legacy_aliases():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert html.count('r2.dev/releases/v2.1.2/ImobHunter-BR-') == 4
    assert "Baixar v2.1.1" not in html
    assert "ImobHunter-BR-Setup-Windows-2.1.1.exe" not in html
