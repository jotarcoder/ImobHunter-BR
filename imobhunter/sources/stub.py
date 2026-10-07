from imobhunter.domain.models import PropertyRecord, SearchRequest, SourceStatus

from .base import SourceAdapter


class ConfiguredSourceStub(SourceAdapter):
    def __init__(self, source_id: str, name: str, category: str) -> None:
        self.source_id = source_id
        self.name = name
        self.category = category

    def status(self) -> SourceStatus:
        return SourceStatus(
            source_id=self.source_id,
            name=self.name,
            status="not_configured",
            message="Source adapter is planned but not configured yet.",
        )

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        return []
