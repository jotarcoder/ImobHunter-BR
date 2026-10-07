from __future__ import annotations

import json
from pathlib import Path

from imobhunter.domain.models import CoverageProject


class DDDCoverageRegistry:
    def __init__(self, projects: tuple[CoverageProject, ...]) -> None:
        self._projects = {project.ddd: project for project in projects}

    def all(self) -> tuple[CoverageProject, ...]:
        return tuple(self._projects.values())

    def get(self, ddd: str) -> CoverageProject | None:
        return self._projects.get(ddd)

    def by_state(self, state: str) -> tuple[CoverageProject, ...]:
        return tuple(
            project for project in self._projects.values() if state.upper() in project.states
        )


def load_ddd_coverage(path: str | Path) -> DDDCoverageRegistry:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise TypeError("DDD coverage data must be a list")
    projects = tuple(
        CoverageProject(
            ddd=str(item["ddd"]),
            states=tuple(item["states"]),
            label=str(item["label"]),
            municipalities=tuple(item.get("municipalities", ())),
            source_ids=tuple(item.get("source_ids", ())),
        )
        for item in payload
    )
    if len(projects) != len({project.ddd for project in projects}):
        raise ValueError("DDD coverage data contains duplicate DDDs")
    return DDDCoverageRegistry(projects)
