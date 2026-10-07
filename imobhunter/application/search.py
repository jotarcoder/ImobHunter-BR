from imobhunter.application.address import normalize_request
from imobhunter.application.intelligence import build_dossier
from imobhunter.application.reconcile import reconcile
from imobhunter.domain.models import SearchRequest
from imobhunter.infrastructure.local_db import LocalDatabase
from imobhunter.sources.registry import SourceRegistry

class SearchService:
    def __init__(self, registry: SourceRegistry, database: LocalDatabase) -> None:
        self.registry = registry
        self.database = database

    def search(self, request: SearchRequest):
        request.validate()
        normalized = normalize_request(request)
        results = []
        for source in self.registry.all():
            try:
                results.extend(source.search(request))
            except Exception:
                continue

        clusters = reconcile(results)
        dossiers = tuple(build_dossier(cluster.identity, cluster.records) for cluster in clusters)
        self.database.record_search(normalized.normalized)
        return normalized, results, dossiers
