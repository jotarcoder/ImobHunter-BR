"""Candidate version matches the published links; native jobs stay gated."""
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_published_version_download_links_match_project_version():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    index = (ROOT / "web/index.html").read_text(encoding="utf-8")
    published = re.search(
        r"releases/v(\d+\.\d+\.\d+)/ImobHunter-BR-Setup-Windows\.exe", index
    )
    assert published is not None
    assert published.group(1) == version
    assert index.count(f"Baixar v{version} →") == 4
    assert "pyarrow>=20,<23" in project["project"]["optional-dependencies"]["desktop"]


def test_one_time_v213_candidate_build_requires_green_main_ci_and_antivirus_gate():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    windows = workflow.split("\n  windows:\n", 1)[1].split("\n  linux:\n", 1)[0]
    assert "github.event_name == 'workflow_run'" in windows
    for name, following in (
        ("linux", "macos-intel"),
        ("macos-intel", "macos-arm"),
        ("macos-arm", "candidate-manifest"),
    ):
        block = workflow.split(f"\n  {name}:\n", 1)[1].split(f"\n  {following}:\n", 1)[0]
        condition = next(line for line in block.splitlines() if line.strip().startswith("if:"))
        assert "github.event_name == 'workflow_dispatch'" in condition
        assert "(github.event_name == 'workflow_run' && needs.meta.outputs.version == '2.1.3')" in condition
    assert "Start-MpScan -ScanType CustomScan" in windows
    assert '$setupPath = (Resolve-Path "packaging/windows/Output/ImobHunter-BR-Setup-Windows.exe").Path' in windows
    assert 'git diff --name-only HEAD^ HEAD -- .github/workflows/release.yml' in workflow
    arm = workflow.split("\n  macos-arm:\n", 1)[1].split("\n  candidate-manifest:\n", 1)[0]
    assert "runs-on: macos-15\n" in arm
    assert "Verify PySide6 and PyArrow native ARM64 extensions" in arm
    assert "pyarrow._parquet" in arm
    assert "Get-AuthenticodeSignature" in windows
    assert "PyArrow native Parquet extension not found" in windows
    assert "NOT published to R2; awaiting manual Windows validation." in windows
    assert "s3 cp" not in windows
