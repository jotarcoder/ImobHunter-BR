from pathlib import Path
from imobhunter.application.search import SearchService
from imobhunter.domain.models import SearchRequest
from imobhunter.infrastructure.local_db import LocalDatabase
from imobhunter.sources.registry import SourceRegistry
from imobhunter.sources.stub import ConfiguredSourceStub

def test_search_records_history(tmp_path: Path):
    database = LocalDatabase(tmp_path / "db.sqlite")
    service = SearchService(SourceRegistry({"stub": ConfiguredSourceStub("stub", "Stub", "test")}), database)

    result = service.search(
        SearchRequest(address="Rua São José", number="42", city="São Paulo", state="SP")
    )

    assert result.normalized.normalized == "RUA SAO JOSE 42"
    assert result.records == ()
    assert result.dossiers == ()
    assert database.search_count() == 1
