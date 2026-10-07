from abc import ABC, abstractmethod

from imobhunter.domain.models import PropertyRecord, SearchRequest, SourceStatus

class SourceAdapter(ABC):
    source_id: str
    name: str

    @abstractmethod
    def status(self) -> SourceStatus:
        raise NotImplementedError

    @abstractmethod
    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        raise NotImplementedError
