"""Release v2.1.0 must never build/publish an obsolete or unverified installer."""
from pathlib import Path
import re
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_desktop_version_is_identical_in_all_packaging_inputs() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = metadata["project"]["version"]
    assert version == "2.1.0"
    package = (ROOT / "imobhunter/__init__.py").read_text(encoding="utf-8")
    windows = (ROOT / "packaging/windows/version_info.txt").read_text(encoding="utf-8")
    inno = (ROOT / "packaging/windows/ImobHunter-BR.iss").read_text(encoding="utf-8")
    assert f'__version__ = "{version}"' in package
    assert f"StringStruct('ProductVersion', '{version}')" in windows
    assert f"StringStruct('FileVersion', '{version}')" in windows
    numeric = ", ".join(version.split(".") + ["0"])
    assert f"filevers=({numeric})" in windows
    assert f"prodvers=({numeric})" in windows
    assert f'#define MyAppVersion "{version}"' in inno
    assert "PySide6==6.8.3" in metadata["project"]["optional-dependencies"]["desktop"]


def test_native_builds_require_approved_ci_and_actual_version_bump() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "workflow_run:" in workflow
    assert 'workflows: ["CI"]' in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.event == 'push'" in workflow
    assert "HEAD^:pyproject.toml" in workflow
    assert 'if [ "$PREVIOUS_VERSION" != "$VERSION" ]; then' in workflow
    assert "should_build: ${{ steps.ref.outputs.should_build }}" in workflow
    assert workflow.count("needs.meta.outputs.should_build == 'true' &&") == 5
    assert "validate-packaging:" in workflow
    assert "if: github.event_name == 'pull_request'" in workflow
    assert "candidate-manifest:" in workflow
    assert "ImobHunter-BR-Checksums-v" in workflow
    assert "ImobHunter-BR-Setup-Windows.exe" in workflow
    assert "ImobHunter-BR-macOS-AppleSilicon.dmg" in workflow


def test_r2_requires_explicit_manual_approval_and_no_workflow_run() -> None:
    workflow = (ROOT / ".github/workflows/publish-r2-installers.yml").read_text(
        encoding="utf-8"
    )
    assert re.search(r"^  workflow_dispatch:", workflow, flags=re.MULTILINE)
    assert not re.search(r"^  workflow_run:", workflow, flags=re.MULTILINE)
    assert "confirm_publish:" in workflow
    assert "if: inputs.confirm_publish == true" in workflow
    assert "default: v2.0.0" not in workflow
    assert "s3://imobhunter-downloads/" in workflow
