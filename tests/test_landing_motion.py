from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_landing_is_institutional_only():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'script src="app.js"' not in html
    assert 'id="demoSearch"' not in html
    assert "Política de Privacidade" in html
    assert "Termos de Uso" in html
    assert "Política de Fontes" in html
    assert "pub-6bd1ab819504434691f4832d98de3cb6.r2.dev" in html
    for asset in (
        "ImobHunter-BR-Setup-Windows.exe",
        "ImobHunter-BR-Linux.AppImage",
        "ImobHunter-BR-macOS-Intel.dmg",
        "ImobHunter-BR-macOS-AppleSilicon.dmg",
    ):
        assert asset in html
    assert "motion-reel" in html
    assert "MOVE TO EXPLORE" not in html
    assert 'class="button primary"' in html
    assert 'class="button"' in html
    css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
    motion = (ROOT / "web" / "motion.js").read_text(encoding="utf-8")
    assert "--button-rx:0deg" in css
    assert "translateZ(var(--button-z))" in css
    assert "--button-rx" in motion
    assert ".hero-copy{\n  text-align:center" in css
    assert "#plataforma,\n#downloads,\n#fontes,\n#privacidade{\n  text-align:center;" in css
    assert "#fontes > .textlink" in css
    assert ".legalbuttons{\n  justify-content:center;" in css
    assert ".sourcegrid .source-card strong" in css
    assert "translateZ(30px)" in css
    assert "--field-x" in css
    assert "--field-x" in motion
    assert "magnetic-cursor" in css
    assert "Magnetic cursor:" in motion
    assert "data-magnetic" in motion
    assert '<strong>GeoSampa</strong>' in html
    assert '<strong>OpenStreetMap</strong>' in html


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
