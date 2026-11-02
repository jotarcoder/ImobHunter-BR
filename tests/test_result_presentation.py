"""Qt-independent tests of the dossier fields and copyable summary."""
from imobhunter.application.intelligence import build_dossier
from imobhunter.application.result_presentation import (
    dossier_caption,
    field_label,
    source_status_label,
    summary_items,
    summary_text,
)
from imobhunter.application.search import SearchResult, SourceSearchResult
from imobhunter.domain.models import NormalizedAddress, PropertyRecord, Provenance


def dossier(*, match: str = "exact", relation: str | None = None):
    return build_dossier(
        "test-id",
        (
            PropertyRecord(
                property_id="010.020.0030-1",
                address="Rua Pamplona, 1578",
                city="São Paulo",
                state="SP",
                block="020",
                lot="0030",
                area_m2=420.0,
                attributes={
                    "source": "geosampa",
                    "iptu_registration_number": "010.020.0030-1",
                    "sql": "010.020.0030-1",
                    "house_number_match": match,
                    "parcel_relation": relation,
                },
                provenance=(Provenance("geosampa", confidence=0.95),),
            ),
        ),
    )


def test_summary_has_unambiguous_labels_and_collapses_duplicate_sql() -> None:
    items = summary_items(dossier())
    assert items.count(("SQL / IPTU", "010.020.0030-1")) == 1
    assert ("Quadra", "020") in items
    assert ("Lote", "0030") in items
    assert ("Área do terreno (m²)", "420.0") in items


def test_neighbors_and_geocoding_are_not_labeled_confirmed() -> None:
    assert dossier_caption(dossier(match="neighboring_parcel", relation="neighbor_candidate")).startswith(
        "Lote vizinho"
    )
    assert "conferir número" in dossier_caption(dossier(match="geocoded_spatial_match"))
    assert "candidato" in dossier_caption(dossier(match="geocoded_spatial_candidate")).lower()
    assert "confirmado" in dossier_caption(dossier(match="exact"))


def test_copy_summary_includes_source_context_and_important_values() -> None:
    item = dossier(match="neighboring_parcel", relation="neighbor_candidate")
    result = SearchResult(
        normalized=NormalizedAddress(original="Rua Pamplona", normalized="RUA PAMPLONA 1578"),
        records=(),
        dossiers=(item,),
        sources=(
            SourceSearchResult("geosampa", "GeoSampa", "ok", 1),
            SourceSearchResult("empty", "Fonte indisponível", "timeout", 0),
        ),
    )
    text = summary_text(result)
    for value in (
        "SQL / IPTU: 010.020.0030-1",
        "Quadra: 020",
        "Lote: 0030",
        "Fontes dos dados: geosampa",
        "Lote vizinho",
        "Tempo limite excedido",
    ):
        assert value in text


def test_source_and_raw_field_labels_keep_provenance() -> None:
    assert source_status_label("no_results") == "Respondeu sem resultados"
    assert "geoportal" in field_label("source_attribute:geoportal:area_terreno")
    assert field_label("attribute:iptu_registration_number") == "SQL / inscrição IPTU"


def test_desktop_dossier_workflow_is_nonmodal_and_copyable() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = (root / "imobhunter" / "ui_results.py").read_text(encoding="utf-8")
    main = (root / "imobhunter" / "ui.py").read_text(encoding="utf-8")
    assert "QTabWidget()" in source
    assert "QSplitter(Qt.Orientation.Horizontal)" in source
    assert "QKeySequence.StandardKey.Copy" in source
    assert "window.setWindowModality(Qt.WindowModality.NonModal)" in source
    assert "window.show()" in source
    assert "SearchResultsWindow(request, map_factory=CadastralMapDialog)" in main
    assert "_search_watchdog" not in main
    assert "dialog = MarketIntelligenceDialog(self)\n        dialog.exec()" not in main
