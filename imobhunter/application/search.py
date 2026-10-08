from dataclasses import dataclass

from imobhunter.application.address import normalize_request
from imobhunter.application.intelligence import PropertyDossier, build_dossier
from imobhunter.application.reconcile import reconcile
from imobhunter.domain.models import NormalizedAddress, PropertyRecord, SearchRequest
from imobhunter.infrastructure.local_db import LocalDatabase
from imobhunter.sources.registry import SourceRegistry


@dataclass(frozen=True)
class SourceSearchResult:
    source_id: str
    name: str
    status: str
    records_count: int
    message: str | None = None


@dataclass(frozen=True)
class SearchResult:
    normalized: NormalizedAddress
    records: tuple[PropertyRecord, ...]
    dossiers: tuple[PropertyDossier, ...]
    sources: tuple[SourceSearchResult, ...] = ()


class SearchService:
    def __init__(self, registry: SourceRegistry, database: LocalDatabase) -> None:
        self.registry = registry
        self.database = database

    def search(self, request: SearchRequest) -> SearchResult:
        request.validate()
        normalized = normalize_request(request)
        records: list[PropertyRecord] = []
        source_results: list[SourceSearchResult] = []

        for source in self.registry.all():
            configured = source.status()
            if configured.status == "not_configured":
                source_results.append(
                    SourceSearchResult(
                        source_id=source.source_id,
                        name=source.name,
                        status="not_configured",
                        records_count=0,
                        message=configured.message,
                    )
                )
                continue

            try:
                source_records = source.search(request)
            except (OSError, RuntimeError, ValueError) as exc:
                source_results.append(
                    SourceSearchResult(
                        source_id=source.source_id,
                        name=source.name,
                        status="error",
                        records_count=0,
                        message=str(exc),
                    )
                )
                continue

            records.extend(source_records)
            source_results.append(
                SourceSearchResult(
                    source_id=source.source_id,
                    name=source.name,
                    status="ok" if source_records else "no_results",
                    records_count=len(source_records),
                    message=None if source_records else "Nenhum imóvel encontrado nesta fonte.",
                )
            )

        records_tuple = tuple(records)
        clusters = reconcile(records_tuple)
        dossiers = tuple(
            build_dossier(cluster.identity, cluster.records) for cluster in clusters
        )
        self.database.record_search(normalized.normalized)
        return SearchResult(
            normalized,
            records_tuple,
            dossiers,
            tuple(source_results),
        )
