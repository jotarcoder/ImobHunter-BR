"""Single PUT recovery bypasses R2 multipart InvalidPart without changing the build."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
YML = (ROOT / ".github/workflows/publish-r2-v2.1.3-single-put-recovery.yml").read_text()


def test_recovery_is_one_time_after_green_main_ci_and_pinned_to_original_build():
    assert 'workflows: ["CI"]' in YML
    assert "github.event.workflow_run.conclusion == 'success'" in YML
    assert "git diff --diff-filter=A --name-only HEAD^ HEAD" in YML
    assert ".github/workflows/publish-r2-v2.1.3-single-put-recovery.yml" in YML
    assert "3b114223155b60e507e0b3a48931644ff8fc624c" in YML
    assert "42046990880" in YML
    assert "releases/v2.1.3" in YML
    assert 'bucket="imobhunter-downloads"' in YML


def test_exact_four_binaries_are_hash_verified_before_direct_r2_upload():
    assert YML.count("  ImobHunter-BR-") >= 4
    assert "sha256sum --check SHA256SUMS" in YML
    assert "aws s3api put-object" in YML
    assert "AWS_REQUEST_CHECKSUM_CALCULATION=when_required" in YML
    assert "aws s3 cp" not in YML
    assert "CompleteMultipartUpload." in YML
    assert YML.index("sha256sum --check SHA256SUMS") < YML.index("aws s3api put-object")
    assert "aws s3api head-object" in YML
    assert "aws s3 rm" not in YML
    assert "aws s3api delete-object" not in YML
    assert "LICENSE_SIGNING_PRIVATE_JWK" not in YML
