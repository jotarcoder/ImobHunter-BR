"""Optional offscreen Qt smoke test (runs when desktop dependencies are present).

No network requests are made. CI without the optional desktop extra skips this
test instead of installing heavyweight Qt just to validate pure data logic.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_QT_APP = None


def _app():
    # Keep the underlying QApplication alive across several smoke tests.
    from PySide6.QtWidgets import QApplication

    global _QT_APP
    if _QT_APP is None:
        _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def test_map_has_selectable_parcels_and_changes_real_zoom(monkeypatch) -> None:
    pytest.importorskip("PySide6")
    from imobhunter.domain.models import PropertyRecord, Provenance
    from imobhunter.ui_cadastral_map import CadastralMapWidget

    # No background HTTP jobs; the native map retains parcel overlays offline.
    monkeypatch.setattr(CadastralMapWidget, "_request_visible_tiles", lambda self: None)

    polygon = (
        '{"type":"Polygon","coordinates":[['
        '[-46.651,-23.551],[-46.650,-23.551],'
        '[-46.650,-23.550],[-46.651,-23.551]]]}'
    )
    parcel = PropertyRecord(
        address="Rua Pamplona",
        city="São Paulo",
        state="SP",
        block="020",
        lot="0030",
        area_m2=150,
        attributes={
            "geometry_geojson": polygon,
            "house_number_match": "geocoded_spatial_match",
            "iptu_registration_number": "010.020.0030-1",
        },
        provenance=(Provenance("geosampa"),),
    )
    app = _app()
    widget = CadastralMapWidget([parcel])
    widget.resize(900, 600)
    widget.show()
    app.processEvents()
    try:
        assert widget._target is not None
        assert widget._zoom == 17
        assert "correspondência espacial" in widget.details.toPlainText().casefold()
        assert "010.020.0030-1" in widget.details.toPlainText()
        assert widget.scene.items()
        widget._change_zoom(1)
        assert widget._zoom == 18
        assert widget.scene.items()
        widget._fit_features()
        assert widget.features[0].has_official_polygon
    finally:
        widget.close()
        app.processEvents()



def test_real_dossier_map_is_offline_copyable_and_keeps_neighbor_separate(monkeypatch) -> None:
    """End-to-end Qt contract: result tab -> polygons -> selection -> clipboard."""
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QGraphicsPathItem

    from imobhunter.application.search import SearchResult, SourceSearchResult
    from imobhunter.domain.models import NormalizedAddress, PropertyRecord, SearchRequest
    from imobhunter.ui_cadastral_map import CadastralMapWidget
    from imobhunter.ui_results import SearchResultsWindow

    # The test must never make any OSM HTTP requests.
    monkeypatch.setattr(CadastralMapWidget, "_request_visible_tiles", lambda self: None)
    app = _app()
    polygon_a = {
        "type": "Polygon",
        "coordinates": [[
            [-46.651, -23.551], [-46.6505, -23.551],
            [-46.6505, -23.550], [-46.651, -23.551],
        ]],
    }
    polygon_b = {
        "type": "Polygon",
        "coordinates": [[
            [-46.6505, -23.551], [-46.650, -23.551],
            [-46.650, -23.550], [-46.6505, -23.551],
        ]],
    }
    import json

    matched = PropertyRecord(
        city="São Paulo", state="SP", address="Rua Exemplo, 100",
        block="021", lot="0042", area_m2=185.0,
        attributes={
            "geometry_geojson": json.dumps(polygon_a),
            "house_number_match": "exact",
            "iptu_registration_number": "010.021.0042-1",
        },
    )
    neighbor = PropertyRecord(
        city="São Paulo", state="SP", address="Rua Exemplo, 102",
        block="021", lot="0043", area_m2=214.0,
        attributes={
            "geometry_geojson": json.dumps(polygon_b),
            "house_number_match": "neighboring_parcel",
            "parcel_relation": "neighbor_candidate",
        },
    )
    request = SearchRequest(
        address="Rua Exemplo", number="100", city="São Paulo", state="SP"
    )
    window = SearchResultsWindow(request)
    window.resize(1050, 680)
    window.show()
    app.processEvents()
    try:
        window.set_result(SearchResult(
            normalized=NormalizedAddress("Rua Exemplo", "RUA EXEMPLO"),
            records=(matched, neighbor),
            dossiers=(),
            sources=(SourceSearchResult(
                "geosampa", "GeoSampa", "ok", 2
            ),),
        ))
        app.processEvents()
        assert window.map_button.isEnabled()
        assert window.tabs.currentWidget() is window.map_tab
        assert window._map_widget is not None
        map_widget = window._map_widget
        assert map_widget._target.record is matched
        polygons = [
            item for item in map_widget.scene.items()
            if isinstance(item, QGraphicsPathItem)
        ]
        assert len(polygons) == 2
        neighbor_item = next(
            item for item in polygons
            if item.data(0).record is neighbor
        )
        neighbor_item.setSelected(True)
        app.processEvents()
        assert map_widget._displayed_record is neighbor
        details = map_widget.details.toPlainText()
        assert "0043" in details
        assert "Não fornecido nesta fonte" in details
        assert "010.021.0042-1" not in details
        map_widget._copy_details()
        assert "0043" in QApplication.clipboard().text()
        assert "010.021.0042-1" not in QApplication.clipboard().text()
        zoom = map_widget._zoom
        map_widget._change_zoom(1)
        app.processEvents()
        assert map_widget._zoom == zoom + 1
        assert len([
            item for item in map_widget.scene.items()
            if isinstance(item, QGraphicsPathItem)
        ]) == 2
        # The dossier remains a normal, interactive top-level window.
        assert window.isVisible()
        assert window.windowModality() == Qt.WindowModality.NonModal
    finally:
        window.close()
        app.processEvents()


def test_map_offline_with_only_geocoded_point_never_draws_fiscal_polygon(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QGraphicsPathItem

    from imobhunter.domain.models import PropertyRecord
    from imobhunter.ui_cadastral_map import CadastralMapWidget

    monkeypatch.setattr(CadastralMapWidget, "_request_visible_tiles", lambda self: None)
    app = _app()
    widget = CadastralMapWidget([PropertyRecord(
        city="Santos", state="SP",
        latitude=-23.934, longitude=-46.326,
        address="Praça Visconde de Mauá",
        attributes={"record_kind": "geocoded_address_only"},
    )])
    widget.show()
    app.processEvents()
    try:
        assert widget._target is None
        assert not any(
            isinstance(item, QGraphicsPathItem) for item in widget.scene.items()
        )
        assert "sem geometria oficial" in widget.status.text().casefold() or (
            "não há geometria oficial" in widget.status.text().casefold()
        )
    finally:
        widget.close()
        app.processEvents()
