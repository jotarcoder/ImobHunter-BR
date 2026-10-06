from datetime import datetime, timezone
from imobhunter.domain.models import SearchRequest
from imobhunter.infrastructure.local_db import LocalDatabase
from imobhunter.sources.registry import SourceRegistry

class SearchService:
    def __init__(self, registry: SourceRegistry, database: LocalDatabase) -> None:
        self.registry, self.database = registry, database

    def search(self, request: SearchRequest):
        _ = datetime.now(timezone.utc)
        results = []
        for source in self.registry.all():
            try:
                results.extend(source.search(request))
            except Exception:
                continue
        return results
