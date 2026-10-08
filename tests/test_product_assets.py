from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


def test_brand_assets_exist() -> None:
    assert (ROOT / "imobhunter" / "assets" / "logo.svg").exists()
    assert (ROOT / "web" / "assets" / "hero.svg").exists()


def test_policy_documents_cover_source_and_privacy_rules() -> None:
    source_policy = (ROOT / "docs" / "DATA_SOURCE_POLICY.md").read_text()
    privacy = (ROOT / "docs" / "PRIVACY_POLICY.md").read_text()
    terms = (ROOT / "docs" / "TERMS_OF_USE.md").read_text()
    for source in ("GeoSampa", "CNEFE", "SINTER", "SNCR", "SICAR", "SIGEF",
                   "CNIR", "CNPJ", "INDE", "ICMBio", "IPHAN", "OpenStreetMap", "IPTU"):
        assert source in source_policy
    assert "local-first" in privacy
    assert "CAPTCHA" in terms


def test_download_center_exposes_all_targets() -> None:
    html = (ROOT / "web" / "index.html").read_text()
    for target in ("Windows", "Linux", "macOS Intel", "macOS Apple Silicon"):
        assert target in html
