"""Guarantee the independent Apple Silicon recovery only builds the missing DMG."""
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/macos-apple-silicon-standalone.yml"
SOURCE_SHA = "b26ebfaf439db046fddf7fa91c5fc3956a207b98"
OLD_RUN = "41527699227"


def test_recovery_cross_builds_arm64_without_requiring_arm_runner() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "name: Rebuild Apple Silicon v2.1.0 (standalone)" in workflow
    assert "runs-on: macos-15-intel" in workflow
    assert workflow.count("runs-on: macos-15-intel") == 1
    assert "runs-on: macos-26" not in workflow
    assert "runs-on: macos-15\n" not in workflow
    assert 'test "$(uname -m)" = "x86_64"' in workflow
    assert 'platform.machine() == "x86_64"' in workflow
    assert "python_bin=" in workflow
    assert "PySide6.QtCore.__file__" in workflow
    assert "--target-arch arm64" in workflow
    assert 'test "$archs" = "arm64"' in workflow
    assert "Bundled Mach-O lacks arm64 slice" in workflow
    assert "lipo -archs" in workflow


def test_build_waits_for_green_main_ci_and_is_one_time_only() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'workflows: ["CI"]' in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.event == 'push'" in workflow
    assert "standalone v2.1.0 Apple Silicon installer" in workflow
    assert "git diff --name-only HEAD^1 HEAD" in workflow
    assert "fetch-depth: 2" in workflow
    assert "workflow_dispatch:" not in workflow
    assert "cancel-in-progress: false" in workflow


def test_uses_identical_v2_1_0_source_as_other_three_builds() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["version"] == "2.1.0"
    assert SOURCE_SHA in workflow
    assert OLD_RUN in workflow
    assert "pyinstaller==6.22.3" in workflow
    assert "pyinstaller-hooks-contrib==2026.9" in workflow
    assert "python -m PyInstaller --clean" in workflow
    assert "ca_bundle=" in workflow


def test_old_three_installers_are_reused_and_four_hashes_verified() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Verify three previous installers are still stored, without rebuilding" in workflow
    assert "Download previous Windows candidate (no rebuild)" in workflow
    assert "Download previous Linux candidate (no rebuild)" in workflow
    assert "Download previous macOS Intel candidate (no rebuild)" in workflow
    for name in (
        "ImobHunter-BR-Setup-Windows.exe",
        "ImobHunter-BR-Linux.AppImage",
        "ImobHunter-BR-macOS-Intel.dmg",
        "ImobHunter-BR-macOS-AppleSilicon.dmg",
    ):
        assert name in workflow
    assert "hdiutil verify -quiet" in workflow
    assert "sha256sum -c ImobHunter-BR-macOS-AppleSilicon.sha256" in workflow
    assert "ImobHunter-BR-v2.1.0-four-platform-checksums" in workflow


def test_recovery_never_publishes_and_does_not_touch_existing_build_jobs() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "publish_release" not in workflow
    assert "aws s3" not in workflow
    assert "cloudflare" not in workflow.lower()
    assert "gh release" not in workflow
    assert "  windows:" not in workflow
    assert "  linux:" not in workflow
    assert "  macos-intel:" not in workflow
