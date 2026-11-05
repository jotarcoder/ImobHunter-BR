"""Regression contract: descriptive cards must not overlap on hover."""
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def test_card_indices_use_document_flow_and_text_stays_flat():
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    marker = "/* Hover readability: text and card indices must stay in normal layout"
    assert marker in css
    fix = css.split(marker, 1)[1]
    assert "position:static" in fix
    assert "transform-style:flat!important" in fix
    assert "transform:none!important" in fix
    assert "line-height:1.65" in fix
    for section in ("#plataforma", "#matricula", "#fontes"):
        assert section in fix
    assert bytesize(css) < 58_000


def bytesize(value: str) -> int:
    return len(value.encode("utf-8"))


def test_five_existing_cards_keep_labels_and_source_links():
    index = (WEB / "index.html").read_text(encoding="utf-8")
    for label in ("Busca", "Inteligência", "Cobertura", "Local-first", "Geocodificação"):
        assert label in index
    for label in ("Endereço e cadastro", "Matrícula com", "Registro oficial"):
        assert label in index
    assert 'href="fontes.html"' in index
    import tomllib

    version = tomllib.loads((WEB.parent / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert f"releases/v{version}/ImobHunter-BR-Setup-Windows.exe" in index
