from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_landing_is_institutional_only():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'script src="app.js"' not in html
    assert 'id="demoSearch"' not in html
    assert "Política de Privacidade" in html
    assert "Termos de Uso" in html
    assert "Política de Fontes" in html
    assert "https://github.com/jotarcoder/ImobHunter-BR/releases" in html
    assert "motion-reel" in html
    assert "MOVE TO EXPLORE" not in html
    assert "motion-reel" in html
    assert "releases/latest/download/ImobHunter-BR-Setup-Windows.exe" in html
    assert 'class="button primary"' in html
    assert 'class="button"' in html
    css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
    motion = (ROOT / "web" / "motion.js").read_text(encoding="utf-8")
    assert "--button-rx:0deg" in css
    assert "translateZ(var(--button-z))" in css
    assert "--button-rx" in motion
    assert ".hero-copy{\n  text-align:center" in css


def test_after_effects_motion_package_exists():
    jsx = ROOT / "motion" / "after-effects" / "ImobHunter_Master_12s.jsx"
    readme = ROOT / "motion" / "after-effects" / "README.md"
    content = jsx.read_text(encoding="utf-8")
    assert jsx.is_file()
    assert readme.is_file()
    for marker in (
        "CAMERA_CINEMATIC",
        "EDITORIAL_GRID",
        "PARTICLE_",
        "CAÇANDO OPORTUNIDADES",
        "IMOBHUNTER_MASTER_12S",
    ):
        assert marker in content
