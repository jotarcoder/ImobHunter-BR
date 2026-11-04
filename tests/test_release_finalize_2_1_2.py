"""Single authorized 2.1.2 release workflow must preserve rollback until links are updated."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def test_212_finalization_requires_green_main_ci_and_one_time_source_diff():
    content=(ROOT/".github/workflows/finalize-v2.1.2-r2.yml").read_text()
    assert 'workflows: ["CI"]' in content
    assert "github.event.workflow_run.conclusion == 'success'" in content
    assert "git diff --name-only HEAD^ HEAD" in content
    assert 'test "$version" = "2.1.2"' in content
    assert "Unexpected" not in content
    assert "2c80e05022993d62eb0319220482dd03b70f5353" in content


def test_212_r2_does_not_delete_previous_release_before_pages_switch():
    content=(ROOT/".github/workflows/finalize-v2.1.2-r2.yml").read_text()
    assert content.count("runs-on: macos-15-intel") == 2
    assert content.count("runs-on: ubuntu-latest") >= 3
    assert "sha256sum -c -" in content
    assert "811db6716b8ab635beddfe30e07b07f835ddc1770e76aa987009ed04b986f537" in content
    assert "aws s3 cp" in content
    assert 'prefix="releases/v2.1.2"' in content
    assert "aws s3 rm" not in content
    assert "aws s3api delete-object" not in content
    assert re.search(r"needs: \[gate, linux, macos-intel, macos-arm\]",content)
    assert 'test "$local_size" = "$remote_size"' in content
