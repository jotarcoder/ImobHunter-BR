from html.parser import HTMLParser
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


class LandingParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.hash_links = []
        self.local_assets = []
        self.download_links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "a":
            href = attrs.get("href", "")
            if href.startswith("#") and len(href) > 1:
                self.hash_links.append(href[1:])
            if "data-download-direct" in attrs:
                self.download_links.append(href)
        if tag == "link" and attrs.get("href", "").endswith((".css", ".svg")):
            self.local_assets.append(attrs["href"])
        if tag == "script" and attrs.get("src"):
            self.local_assets.append(attrs["src"])


def test_landing_internal_links_resolve():
    parser = LandingParser()
    parser.feed((WEB / "index.html").read_text(encoding="utf-8"))
    assert parser.ids, "Landing page should expose section IDs"
    missing = sorted(set(parser.hash_links) - parser.ids)
    assert not missing, f"Broken in-page links: {missing}"


def test_landing_local_assets_exist():
    parser = LandingParser()
    parser.feed((WEB / "index.html").read_text(encoding="utf-8"))
    missing = [
        asset for asset in parser.local_assets
        if not (WEB / asset.lstrip("/")).is_file()
    ]
    assert not missing, f"Missing local assets: {missing}"


def test_download_links_use_expected_direct_navigation():
    parser = LandingParser()
    parser.feed((WEB / "index.html").read_text(encoding="utf-8"))
    assert len(parser.download_links) >= 4, "Expected the four platform download links"
    assert all(link.startswith("https://") for link in parser.download_links)
    assert "data-download-direct" in (WEB / "index.html").read_text(encoding="utf-8")


def test_motion_respects_reduced_motion_and_caches_scroll_targets():
    motion = (WEB / "motion.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion: reduce" in motion
    assert "@media(prefers-reduced-motion:reduce)" in css
    assert "const sections = document.querySelectorAll('main section')" in motion
    assert "const motionReels = stage ? stage.querySelectorAll('.motion-reel') : []" in motion
    assert "document.querySelectorAll('main section').forEach" not in motion


def test_pages_security_headers_are_configured():
    headers = (WEB / "_headers").read_text(encoding="utf-8")
    for expected in (
        "X-Content-Type-Options: nosniff",
        "Referrer-Policy: strict-origin-when-cross-origin",
        "X-Frame-Options: DENY",
        "frame-ancestors 'none'",
        "object-src 'none'",
    ):
        assert expected in headers
