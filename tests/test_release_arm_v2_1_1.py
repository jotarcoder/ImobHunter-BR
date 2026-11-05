"""Native Apple Silicon packaging must verify real ARM64 libraries and checksums."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_builds_apple_silicon_with_native_arm64_and_checksum_gate():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    arm = workflow.split("\n  macos-arm:\n", 1)[1].split("\n  candidate-manifest:\n", 1)[0]
    assert "runs-on: macos-15\n" in arm
    assert "Verify native Apple Silicon ARM64 host" in arm
    assert "pyarrow._parquet" in arm
    assert "Native ARM64 wheel missing" in arm
    assert "runs-on: macos-26" not in arm
    assert "ref: ${{ needs.meta.outputs.ref }}" in arm
    assert "--target-arch arm64" in arm
    assert 'test "$(lipo -archs "$binary")" = "arm64"' in arm
    assert "Bundled native binary missing ARM64 slice" in arm
    assert "pyinstaller==6.22.3" in arm
    assert "pyinstaller-hooks-contrib==2026.9" in arm
    assert "hdiutil verify -quiet" in arm
    assert "name: ImobHunter-BR-macOS-AppleSilicon" in arm
    manifest = workflow.split("\n  candidate-manifest:\n", 1)[1]
    for item in (
        "ImobHunter-BR-Setup-Windows.exe",
        "ImobHunter-BR-Linux.AppImage",
        "ImobHunter-BR-macOS-Intel.dmg",
        "ImobHunter-BR-macOS-AppleSilicon.dmg",
    ):
        assert item in manifest
    assert "sha256sum" in manifest
    assert "NOT published to R2" in manifest
