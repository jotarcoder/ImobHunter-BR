"""One-time owner-approved R2 publication must be source-pinned and hash-verified."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / ".github/workflows/publish-r2-v2.1.3-approved.yml").read_text(encoding="utf-8")


def test_publisher_only_runs_after_green_main_ci_on_creation_commit():
    assert 'workflows: ["CI"]' in SCRIPT
    assert "github.event.workflow_run.conclusion == 'success'" in SCRIPT
    assert "github.event.workflow_run.event == 'push'" in SCRIPT
    assert "github.event.workflow_run.head_branch == 'main'" in SCRIPT
    assert 'git diff --diff-filter=A --name-only HEAD^ HEAD' in SCRIPT
    assert 'echo "approved=false"' in SCRIPT
    assert 'test "$CI_SHA" = "$remote_main"' in SCRIPT
    assert '"2.1.3"' in SCRIPT
    assert "3b114223155b60e507e0b3a48931644ff8fc624c" in SCRIPT
    assert "42046990880" in SCRIPT


def test_four_exact_installers_verified_before_any_r2_upload():
    expected = {
        "ImobHunter-BR-Setup-Windows.exe": "71663757b32f896cc7791a47e786c46c56254b593313d8bd1cec4071dcb18bc5",
        "ImobHunter-BR-Linux.AppImage": "bc80d1cf785e5a5b3f0f6257dc8be526e5e296458b5bd605bbc2c96831aea26a",
        "ImobHunter-BR-macOS-Intel.dmg": "41a248b144c690af002525a7e9b954695a46aefad1dfacab6caf98a78b648abd",
        "ImobHunter-BR-macOS-AppleSilicon.dmg": "b3b4fa04a2f3418087deaefd2d47ba5cc63dbdb655465c02f65a1ee71316c26d",
    }
    for name, sha256 in expected.items():
        assert f"{sha256}  {name}" in SCRIPT
    assert SCRIPT.index("sha256sum --check SHA256SUMS") < SCRIPT.index('aws s3 cp "$file"')
    assert 'prefix="releases/v2.1.3"' in SCRIPT
    assert 'bucket="imobhunter-downloads"' in SCRIPT
    assert 'aws s3api head-object' in SCRIPT
    assert 'content-disposition:[[:space:]]*attachment' in SCRIPT
    assert "aws s3 rm" not in SCRIPT
    assert "aws s3api delete-object" not in SCRIPT
    assert "LICENSE_SIGNING_PRIVATE_JWK" not in SCRIPT
