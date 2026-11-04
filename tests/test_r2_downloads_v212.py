"""Site v2.1.2 must use only built versioned R2 artifacts (not stale root files)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web/index.html").read_text(encoding="utf-8")
BASE = "https://pub-6bd1ab819504434691f4832d98de3cb6.r2.dev/releases/v2.1.2/"


def test_all_four_downloads_are_v212_versioned_objects():
    expected = (
        "ImobHunter-BR-Setup-Windows.exe",
        "ImobHunter-BR-Linux.AppImage",
        "ImobHunter-BR-macOS-Intel.dmg",
        "ImobHunter-BR-macOS-AppleSilicon.dmg",
    )
    for file in expected:
        assert f'href="{BASE}{file}"' in HTML
    assert HTML.count("Baixar v2.1.2 →") == 4
    assert "ImobHunter-BR-Setup-Windows-2.1.1.exe" not in HTML
    assert "Baixar v2.1.1" not in HTML


def test_site_version_is_institutional_and_does_not_claim_guaranteed_fiscal_access():
    assert "A versão 2.1.2 inclui conectores" in HTML
    assert "nenhum conector garante SQL/IPTU por endereço" in HTML
    assert "data-download-direct" in HTML
