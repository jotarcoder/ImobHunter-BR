from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass

from imobhunter.application.address import normalize_request
from imobhunter.application.intelligence import PropertyDossier, build_dossier
from imobhunter.application.reconcile import reconcile
from imobhunter.domain.models import NormalizedAddress, PropertyRecord, SearchRequest
from imobhunter.infrastructure.local_db import LocalDatabase
from imobhunter.sources.base import SourceAdapter
from imobhunter.sources.custom_municipal import CustomMunicipalAdapter
from imobhunter.sources.registry import SourceRegistry

DEFAULT_SOURCE_TIMEOUT_SECONDS = 25.0
MAX_PARALLEL_SOURCES = 16


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
    def __init__(
        self,
        registry: SourceRegistry,
        database: LocalDatabase,
        *,
        source_timeout_seconds: float = DEFAULT_SOURCE_TIMEOUT_SECONDS,
        max_parallel_sources: int = MAX_PARALLEL_SOURCES,
    ) -> None:
        if source_timeout_seconds <= 0:
            raise ValueError("source_timeout_seconds must be greater than zero")
        if max_parallel_sources < 1:
            raise ValueError("max_parallel_sources must be at least one")
        self.registry = registry
        self.database = database
        self.source_timeout_seconds = source_timeout_seconds
        self._executor = ThreadPoolExecutor(
            max_workers=max_parallel_sources,
            thread_name_prefix="imobhunter-source",
        )

    @staticmethod
    def _search_source(
        source: SourceAdapter,
        request: SearchRequest,
    ) -> tuple[SourceSearchResult, list[PropertyRecord]]:
        try:
            configured = source.status()
            if configured.status == "not_configured":
                return (
                    SourceSearchResult(
                        source_id=source.source_id,
                        name=source.name,
                        status="not_configured",
                        records_count=0,
                        message=configured.message,
                    ),
                    [],
                )

            records = source.search(request)
            # Municipal adapters retain the HTTP/TLS/timeout diagnosis and may
            # return [] to preserve the rest of the search. Do not misreport a
            # failed endpoint as "no cadastral result" for this address.
            if source.source_id == "official_municipal_services" and not records:
                errors = getattr(source, "last_errors", {})
                if isinstance(errors, dict) and request.city:
                    failure = next(
                        (
                            str(message) for city, message in errors.items()
                            if str(city).casefold() == request.city.casefold()
                        ),
                        None,
                    )
                    if failure:
                        return (
                            SourceSearchResult(
                                source_id=source.source_id, name=source.name,
                                status="error", records_count=0,
                                message=f"Falha na fonte municipal: {failure}",
                            ),
                            [],
                        )
            return (
                SourceSearchResult(
                    source_id=source.source_id,
                    name=source.name,
                    status="ok" if records else "no_results",
                    records_count=len(records),
                    message=None if records else "Nenhum imóvel encontrado nesta fonte.",
                ),
                records,
            )
        except Exception as exc:  # noqa: BLE001 - isolate each adapter failure.
            return (
                SourceSearchResult(
                    source_id=source.source_id,
                    name=source.name,
                    status="error",
                    records_count=0,
                    message=f"{type(exc).__name__}: {exc}",
                ),
                [],
            )

    def search(self, request: SearchRequest) -> SearchResult:
        request.validate()
        normalized = normalize_request(request)
        # User-added municipal adapters are considered only for their exact
        # municipality/UF; never report "no results" from a city not searched.
        sources = [
            source for source in self.registry.all()
            if not isinstance(source, CustomMunicipalAdapter)
            or source.definition.matches(request.city, request.state)
        ]
        results: list[tuple[SourceSearchResult, list[PropertyRecord]] | None] = [
            None
        ] * len(sources)
        future_indices: dict[Future[tuple[SourceSearchResult, list[PropertyRecord]]], int] = {
            self._executor.submit(self._search_source, source, request): index
            for index, source in enumerate(sources)
        }

        completed, pending = wait(
            future_indices,
            timeout=self.source_timeout_seconds,
        )
        for future in completed:
            index = future_indices[future]
            try:
                results[index] = future.result()
            except Exception as exc:  # noqa: BLE001 - defensive executor boundary.
                source = sources[index]
                results[index] = (
                    SourceSearchResult(
                        source_id=source.source_id,
                        name=source.name,
                        status="error",
                        records_count=0,
                        message=f"{type(exc).__name__}: {exc}",
                    ),
                    [],
                )

        for future in pending:
            index = future_indices[future]
            future.cancel()
            source = sources[index]
            results[index] = (
                SourceSearchResult(
                    source_id=source.source_id,
                    name=source.name,
                    status="timeout",
                    records_count=0,
                    message=(
                        "A fonte excedeu o limite de "
                        f"{self.source_timeout_seconds:g} segundos; "
                        "os resultados das demais fontes foram preservados."
                    ),
                ),
                [],
            )

        records: list[PropertyRecord] = []
        source_results: list[SourceSearchResult] = []
        for result in results:
            if result is None:
                continue
            source_result, source_records = result
            source_results.append(source_result)
            records.extend(source_records)

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
