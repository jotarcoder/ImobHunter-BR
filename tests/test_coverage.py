import json

import pytest

from imobhunter.application.coverage import DDDCoverageRegistry, load_ddd_coverage
from imobhunter.domain.models import CoverageProject


def test_ddd_registry_has_all_brazilian_codes(tmp_path) -> None:
    path = tmp_path / "ddds.json"
    path.write_text(
        json.dumps([
            {"ddd": "11", "states": ["SP"], "label": "11 • SP"},
            {"ddd": "61", "states": ["DF", "GO"], "label": "61 • DF/GO"},
            {"ddd": "99", "states": ["MA"], "label": "99 • MA"},
        ]),
        encoding="utf-8",
    )
    registry = load_ddd_coverage(path)
    assert registry.get("11").states == ("SP",)
    assert registry.get("61").states == ("DF", "GO")
    assert registry.by_state("ma")[0].ddd == "99"


def test_ddd_project_requires_two_digit_code() -> None:
    with pytest.raises(ValueError, match="two digits"):
        CoverageProject(ddd="1", states=("SP",), label="1 • SP")


def test_ddd_registry_rejects_duplicate_codes(tmp_path) -> None:
    path = tmp_path / "ddds.json"
    path.write_text(
        json.dumps([
            {"ddd": "11", "states": ["SP"], "label": "11 • SP"},
            {"ddd": "11", "states": ["SP"], "label": "11 • SP duplicate"},
        ]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_ddd_coverage(path)
