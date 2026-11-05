"""Retry only the failed R2 transfer with supported AWS CLI arguments."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
YML = (ROOT / ".github/workflows/publish-r2-v2.1.3-cli-output-recovery.yml").read_text()


def test_r2_recovery_is_one_time_ci_green_and_original_build_only():
    assert 'workflows: ["CI"]' in YML
    assert "github.event.workflow_run.conclusion == 'success'" in YML
    assert "git diff --diff-filter=A --name-only HEAD^ HEAD" in YML
    assert "publish-r2-v2.1.3-cli-output-recovery.yml" in YML
    assert "3b114223155b60e507e0b3a48931644ff8fc624c" in YML
    assert "42046990880" in YML
    assert 'prefix="releases/v2.1.3"' in YML
    assert 'bucket="imobhunter-downloads"' in YML


def test_r2_put_never_uses_invalid_output_or_multipart():
    assert "aws s3api put-object" in YML
    assert "--output json >/dev/null" in YML
    assert "--output none" not in YML.split("  publish:", 1)[1]
    assert "aws s3 cp" not in YML
    assert "AWS_REQUEST_CHECKSUM_CALCULATION=when_required" in YML
    assert "sha256sum --check SHA256SUMS" in YML
    assert YML.index("sha256sum --check SHA256SUMS") < YML.index("aws s3api put-object")
    assert "head-object" in YML
    assert 'if [ "$local_size" != "$remote_size" ]; then' in YML
    assert "content-disposition:[[:space:]]*attachment" in YML
    assert "aws s3 rm" not in YML
    assert "aws s3api delete-object" not in YML


def test_approved_four_sha256_digests_unchanged():
    for sha256, name in (
        ("71663757b32f896cc7791a47e786c46c56254b593313d8bd1cec4071dcb18bc5", "ImobHunter-BR-Setup-Windows.exe"),
        ("bc80d1cf785e5a5b3f0f6257dc8be526e5e296458b5bd605bbc2c96831aea26a", "ImobHunter-BR-Linux.AppImage"),
        ("41a248b144c690af002525a7e9b954695a46aefad1dfacab6caf98a78b648abd", "ImobHunter-BR-macOS-Intel.dmg"),
        ("b3b4fa04a2f3418087deaefd2d47ba5cc63dbdb655465c02f65a1ee71316c26d", "ImobHunter-BR-macOS-AppleSilicon.dmg"),
    ):
        assert f"{sha256}  {name}" in YML
