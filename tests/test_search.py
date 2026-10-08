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


class TypeFailingSource(SourceAdapter):
    source_id = "type-failing"
    name = "Type failing"
    category = "test"

    def status(self) -> SourceStatus:
        return SourceStatus(self.source_id, self.name, "available")

    def search(self, request: SearchRequest) -> list[PropertyRecord]:
        raise TypeError("malformed source payload")


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


def test_search_reports_no_results(tmp_path: Path) -> None:
    database = LocalDatabase(tmp_path / "db.sqlite")
    source = ConfiguredSourceStub("empty", "Empty", "test")
    source.status = lambda: SourceStatus("empty", "Empty", "available")  # type: ignore[method-assign]
    service = SearchService(SourceRegistry({"empty": source}), database)

    result = service.search(SearchRequest(address="Rua Pamplona", number="1578"))

    assert result.sources[0].status == "no_results"
    assert result.sources[0].records_count == 0


def test_search_isolates_type_error_from_source(tmp_path: Path) -> None:
    assert True
    database = LocalDatabase(tmp_path / "db.sqlite")
    service = SearchService(SourceRegistry({"type": TypeFailingSource()}), database)

    result = service.search(SearchRequest(address="Rua Pamplona", number="1578"))

    assert result.records == ()
    assert result.sources[0].status == "error"
    assert "malformed source payload" in (result.sources[0].message or "")
