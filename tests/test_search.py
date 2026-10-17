from pathlib import Path

from imobhunter.application.search import SearchService
from imobhunter.domain.models import PropertyRecord, Provenance, SearchRequest, SourceStatus
from imobhunter.infrastructure.local_db import LocalDatabase
from imobhunter.sources.base import SourceAdapter
from imobhunter.sources.registry import SourceRegistry
from imobhunter.sources.stub import ConfiguredSourceStub


class FailingSource(SourceAdapter):
    source_id = "failing"
    name = "Failing"
    category = "test"

    def status(self) -> SourceStatus:
        return SourceStatus(self.source_id, self.name, "available")

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        raise RuntimeError("source unavailable")


class NetworkFailingSource(SourceAdapter):
    source_id = "network_failing"
    name = "Network Failing"
    category = "test"

    def status(self) -> SourceStatus:
        return SourceStatus(self.source_id, self.name, "available")

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        raise OSError("network unavailable")


class RecordSource(SourceAdapter):
    source_id = "records"
    name = "Records"
    category = "test"

    def status(self) -> SourceStatus:
        return SourceStatus(self.source_id, self.name, "available")

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        return [
            PropertyRecord(
                property_id="P1",
                address="R PAMPLONA",
                block="020",
                lot="0030",
                provenance=(Provenance(self.source_id, confidence=0.9),),
            )
        ]


def test_search_records_history(tmp_path: Path) -> None:
    database = LocalDatabase(tmp_path / "db.sqlite")
    service = SearchService(
        SourceRegistry({"stub": ConfiguredSourceStub("stub", "Stub", "test")}),
        database,
    )

    result = service.search(
        SearchRequest(address="Rua São José", number="42", city="São Paulo", state="SP")
    )

    assert result.normalized.normalized == "RUA SAO JOSE 42"
    assert result.records == ()
    assert result.dossiers == ()
    assert result.sources[0].status == "not_configured"
    assert database.search_count() == 1
    service._executor.shutdown(wait=True, cancel_futures=True)


def test_search_isolates_source_failure_and_keeps_other_results(tmp_path: Path) -> None:
    database = LocalDatabase(tmp_path / "db.sqlite")
    registry = SourceRegistry({})
    registry.register(FailingSource())
    registry.register(RecordSource())
    service = SearchService(registry, database)

    result = service.search(SearchRequest(address="Rua Pamplona", number="1578"))

    assert len(result.records) == 1
    assert len(result.dossiers) == 1
    assert [(item.source_id, item.status) for item in result.sources] == [
        ("failing", "error"),
        ("records", "ok"),
    ]
    assert "source unavailable" in (result.sources[0].message or "")
    service._executor.shutdown(wait=True, cancel_futures=True)


def test_search_reports_no_results(tmp_path: Path) -> None:
    database = LocalDatabase(tmp_path / "db.sqlite")
    source = ConfiguredSourceStub("empty", "Empty", "test")
    source.status = lambda: SourceStatus("empty", "Empty", "available")  # type: ignore[method-assign]
    service = SearchService(SourceRegistry({"empty": source}), database)

    result = service.search(SearchRequest(address="Rua Pamplona", number="1578"))

    assert result.sources[0].status == "no_results"
    assert result.sources[0].records_count == 0
    service._executor.shutdown(wait=True, cancel_futures=True)


def test_search_isolates_source_network_failure(tmp_path: Path) -> None:
    database = LocalDatabase(tmp_path / "db.sqlite")
    registry = SourceRegistry({})
    registry.register(NetworkFailingSource())
    registry.register(RecordSource())
    service = SearchService(registry, database)

    result = service.search(SearchRequest(address="Rua Pamplona", number="1578"))

    assert len(result.records) == 1
    assert [(item.source_id, item.status) for item in result.sources] == [
        ("network_failing", "error"),
        ("records", "ok"),
    ]
    assert "network unavailable" in (result.sources[0].message or "")
    service._executor.shutdown(wait=True, cancel_futures=True)


class StatusFailingSource(SourceAdapter):
    source_id = "status_failing"
    name = "Status Failing"
    category = "test"

    def status(self) -> SourceStatus:
        raise TypeError("broken source metadata")

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        return []


def test_search_isolates_source_status_failure(tmp_path: Path) -> None:
    database = LocalDatabase(tmp_path / "db.sqlite")
    registry = SourceRegistry({})
    registry.register(StatusFailingSource())
    registry.register(RecordSource())
    service = SearchService(registry, database)

    result = service.search(SearchRequest(address="Rua Pamplona", number="1578"))

    assert len(result.dossiers) == 1
    assert result.sources[0].status == "error"
    assert "broken source metadata" in (result.sources[0].message or "")
    service._executor.shutdown(wait=True, cancel_futures=True)


class SlowSource(SourceAdapter):
    source_id = "slow"
    name = "Slow"
    category = "test"

    def status(self) -> SourceStatus:
        return SourceStatus(self.source_id, self.name, "available")

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        import time

        time.sleep(1.0)
        return []


def test_search_runs_sources_concurrently_and_times_out_slow_source(tmp_path: Path) -> None:
    import time

    database = LocalDatabase(tmp_path / "db.sqlite")
    registry = SourceRegistry({})
    registry.register(SlowSource())
    registry.register(RecordSource())
    service = SearchService(
        registry,
        database,
        source_timeout_seconds=0.05,
        max_parallel_sources=2,
    )

    started = time.monotonic()
    try:
        result = service.search(SearchRequest(address="Rua Pamplona", number="1578"))
        elapsed = time.monotonic() - started
    finally:
        service._executor.shutdown(wait=True, cancel_futures=True)

    assert elapsed < 0.5
    assert len(result.records) == 1
    assert [(item.source_id, item.status) for item in result.sources] == [
        ("slow", "timeout"),
        ("records", "ok"),
    ]
    assert "limite de 0.05 segundos" in (result.sources[0].message or "")
