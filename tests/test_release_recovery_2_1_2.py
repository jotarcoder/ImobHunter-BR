"""ARM64 PyArrow must be built natively, while three prior candidates stay unchanged."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
YML = (ROOT / ".github/workflows/recover-v2.1.2-macos-arm.yml").read_text()


def test_arm_recovery_is_native_and_single_use():
    assert "runs-on: macos-15" in YML
    assert "runs-on: macos-15-intel" not in YML
    assert 'test "$(uname -m)" = "arm64"' in YML
    assert "pyarrow._parquet" in YML
    assert "pyarrow._acero" in YML
    assert "--target-arch arm64" in YML
    assert "git diff --name-only HEAD^ HEAD" in YML
    assert 'test "$EXPECTED" = "$current_main"' in YML


def test_known_binaries_reused_and_publication_is_all_or_nothing():
    assert "41892355706" in YML
    assert "41898423206" in YML
    assert "811db6716b8ab635beddfe30e07b07f835ddc1770e76aa987009ed04b986f537" in YML
    assert "gh run download" in YML
    assert "name: ImobHunter-BR-macOS-AppleSilicon" in YML
    assert "needs: [gate, macos-arm]" in YML
    assert "releases/v2.1.2" in YML
    assert "releases/v2.1.1" not in YML
    assert "aws s3 rm" not in YML


def test_recovery_gate_handles_new_commit_and_full_ancestry():
    assert "github.event.workflow_run.head_sha == '63a50a91d8b80dfd7eff4d0f05f79f1050eb160c'" in YML
    assert "fetch-depth: 0" in YML
    assert 'echo "ready=false" >> "$GITHUB_OUTPUT"' in YML
    assert "git diff --name-only 8a867e4aed5b5d7591dc397a79305c1e2f8a927e HEAD" in YML
    assert "finalize-v2" in YML
