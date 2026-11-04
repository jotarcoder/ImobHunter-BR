"""R2 cutover is guarded by a successfully deployed v2.1.2 landing."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
P=(ROOT/".github/workflows/r2-v2.1.2-cutover.yml").read_text()


def test_r2_cutover_only_after_pages_success_and_new_objects():
    assert 'workflows: ["Deploy institutional website to Cloudflare Pages"]' in P
    assert "github.event.workflow_run.conclusion == 'success'" in P
    assert 'grep -Fq \'Baixar v2.1.1\'' not in P
    assert "test \"$size\" -gt 10000000" in P
    assert "releases/v2.1.2/build-manifest.txt" in P
    assert "curl -fsSL --retry 2" in P


def test_old_release_deletion_runs_after_alias_copy():
    assert "Only now delete all previous v2.1.1 R2 objects" in P
    assert P.index("Replace four stable public aliases") < P.index("Only now delete all previous")
    assert "s3://imobhunter-downloads/releases/v2.1.1/" in P
    assert "ImobHunter-BR-Setup-Windows-2.1.1.exe" in P
    assert "s3://imobhunter-downloads/releases/v2.1.2/" in P
