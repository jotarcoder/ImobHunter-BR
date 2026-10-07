from dataclasses import dataclass

from imobhunter.application.address import normalize_request
from imobhunter.application.intelligence import PropertyDossier, build_dossier
from imobhunter.application.reconcile import reconcile
from imobhunter.domain.models import NormalizedAddress, PropertyRecord, SearchRequest
from imobhunter.infrastructure.local_db import LocalDatabase
from imobhunter.sources.registry import SourceRegistry

@dataclass(frozen=True)
class SearchResult:
    normalized: NormalizedAddress
    records: tuple[PropertyRecord, ...]
    dossiers: tuple[PropertyDossier, ...]

class SearchService:
    def __init__(self, registry: SourceRegistry, database: LocalDatabase) -> None:
        self.registry = registry
        self.database = database

    def search(self, request: SearchRequest) -> SearchResult:
        request.validate()
        normalized = normalize_request(request)
        records: list[PropertyRecord] = []

        for source in self.registry.all():
            records.extend(source.search(request))

        records_tuple = tuple(records)
        clusters = reconcile(records_tuple)
        dossiers = tuple(
            build_dossier(cluster.identity, cluster.records) for cluster in clusters
        )
        self.database.record_search(normalized.normalized)
        return SearchResult(normalized, records_tuple, dossiers)
