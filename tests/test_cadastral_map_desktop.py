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


@pytest.fixture(scope="module", autouse=True)
def _release_qt_before_python_interpreter_shutdown():
    """Qt widgets must be freed while QApplication and Qt modules are alive.

    Without an explicit teardown, interpreter-wide garbage collection may
    destroy QObject wrappers after Qt's shared objects have gone away.
    """
    global _QT_APP
    yield
    if _QT_APP is None:
        return

    import gc

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from imobhunter import ui_cadastral_map

    app = _QT_APP
    QApplication.closeAllWindows()
    app.processEvents()
    pool = ui_cadastral_map._MAP_TILE_POOL
    if pool is not None:
        pool.waitForDone(5000)
        ui_cadastral_map._MAP_TILE_POOL = None
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    app.quit()
    _QT_APP = None
    del pool
    del app
    gc.collect()



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



def test_municipal_settings_show_actual_urls_and_test_without_blocking(monkeypatch):
    """The user sees the exact adapter endpoint; a probe runs asynchronously."""
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QThreadPool

    from imobhunter.application.municipal_endpoints import settings_endpoint_rows
    from imobhunter.application.source_probe import EndpointProbe
    from imobhunter.sources.registry import build_default_registry
    from imobhunter.ui_settings import SourceSettingsDialog
    import imobhunter.ui_settings as settings_module

    # Deterministic fake probe; clicking the button never performs HTTP.
    calls = []
    def fake_probe(item):
        calls.append(item["id"])
        return EndpointProbe(
            "responded", "GetCapabilities WFS respondeu com XML válido", 18
        )
    monkeypatch.setattr(settings_module, "probe_endpoint", fake_probe)

    app = _app()
    dialog = SourceSettingsDialog(build_default_registry())
    dialog.show()
    app.processEvents()
    try:
        expected = {item["id"]: item for item in settings_endpoint_rows()}
        for id_, field in dialog.municipal_endpoint_rows.items():
            assert field.isReadOnly()
            assert field.text() == expected[id_]["url"]
        assert dialog.geosampa_url.text().startswith("https://")
        assert "Indisponibilidade" in (
            dialog._municipal_probe_labels["bertioga"].text()
        )
        button = dialog._municipal_probe_buttons["santos"]
        button.click()
        # Complete the small simulated QRunnable, then deliver the Qt signal.
        assert QThreadPool.globalInstance().waitForDone(3000)
        app.processEvents()
        assert calls == ["santos"]
        assert button.isEnabled()
        assert "Metadados acessíveis" in (
            dialog._municipal_probe_labels["santos"].text()
        )
        assert "Não confirma SQL/IPTU" in (
            dialog._municipal_probe_labels["santos"].text()
        )
    finally:
        dialog.close()
        app.processEvents()



def test_screen_fit_math_respects_taskbar_monitor_origin_and_logical_dpi() -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QRect, QSize
    from imobhunter.ui_responsive import geometry_within_screen

    for available in (
        QRect(0, 0, 1366, 728),  # Windows taskbar occupies the bottom.
        QRect(0, 0, 800, 560),  # Low-resolution display.
        QRect(1920, 50, 910, 490),  # Secondary display with 150% DPI scaling.
        QRect(-1024, 0, 1024, 600),  # Secondary monitor to the left.
    ):
        desired = geometry_within_screen(
            available, QSize(1280, 820), QSize(650, 450),
        )
        assert available.contains(desired)
        assert desired.width() <= available.width() - 24
        assert desired.height() <= available.height() - 24
        assert desired.width() > 0 and desired.height() > 0


def test_settings_save_and_close_buttons_fit_inside_available_screen() -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QPushButton

    from imobhunter.sources.registry import build_default_registry
    from imobhunter.ui_settings import SourceSettingsDialog

    app = _app()
    window = SourceSettingsDialog(build_default_registry())
    window.show()
    app.processEvents()
    try:
        assert window.screen().availableGeometry().contains(window.geometry())
        for caption in ("Validar configurações", "Salvar configurações", "Fechar"):
            button = next(
                child for child in window.findChildren(QPushButton)
                if child.text() == caption
            )
            top_left = button.mapTo(window, QPoint(0, 0))
            assert top_left.y() >= 0
            assert top_left.y() + button.height() <= window.height()
            assert top_left.x() >= 0
            assert top_left.x() + button.width() <= window.width()
    finally:
        window.close()
        app.processEvents()


def test_market_tabs_reflow_and_company_table_scroll_without_truncating_buttons(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QHeaderView

    import builtins
    from pathlib import Path
    from imobhunter.ui_market import MarketIntelligenceDialog

    # Keep the test offline and avoid launching a Chromium subprocess.
    original_import = builtins.__import__

    def no_webengine(name, *args, **kwargs):
        if name.startswith("PySide6.QtWebEngine"):
            raise ImportError("No WebEngine during desktop layout test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_webengine)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    app = _app()
    window = MarketIntelligenceDialog()
    window.show()
    app.processEvents()
    try:
        assert window.screen().availableGeometry().contains(window.geometry())
        assert window.tabs.widget(0) is window.search_scroll
        assert window.tabs.widget(1) is window.results_scroll
        window.resize(760, min(540, window.screen().availableGeometry().height()))
        app.processEvents()
        assert window._action_grid.itemAtPosition(3, 1) is not None
        assert window._action_grid.itemAtPosition(0, 3) is None
        for table in (window.table, window.results_table):
            assert not table.horizontalHeader().stretchLastSection()
            assert table.horizontalHeader().sectionResizeMode(0) == (
                QHeaderView.ResizeMode.Interactive
            )
            assert table.horizontalScrollBarPolicy() == (
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            assert sum(table.columnWidth(i) for i in range(8)) > table.viewport().width()
        # Switching to results must target the scroll host, not the old page.
        window.tabs.setCurrentWidget(window.results_scroll)
        assert window.tabs.currentWidget() is window.results_scroll
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_local_cnpj_browser_filters_and_table_fit_small_windows(tmp_path) -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt

    from imobhunter.ui_market import ReceitaBrowseDialog

    app = _app()
    browser = ReceitaBrowseDialog(tmp_path / "companies.sqlite3")
    browser.show()
    app.processEvents()
    try:
        assert browser.screen().availableGeometry().contains(browser.geometry())
        assert browser.table.horizontalScrollBarPolicy() == (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        assert browser.table.columnWidth(0) >= 200
        assert browser.table.columnWidth(5) >= 300
        assert browser.findChildren(type(browser.query))
    finally:
        browser.close()
        browser.deleteLater()
        app.processEvents()



def test_main_window_and_integrations_keep_controls_inside_screen(tmp_path) -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QDialog, QPushButton, QScrollArea

    from imobhunter.application.coverage import DDDCoverageRegistry
    from imobhunter.application.search import SearchService
    from imobhunter.infrastructure.local_db import LocalDatabase
    from imobhunter.sources.registry import build_default_registry
    from imobhunter.ui import MainWindow

    app = _app()
    window = MainWindow(
        SearchService(build_default_registry(), LocalDatabase(tmp_path / "cache.sqlite3")),
        DDDCoverageRegistry(()),
    )
    window.show()
    app.processEvents()
    try:
        assert window.screen().availableGeometry().contains(window.geometry())
        assert window.content_scroll.widget() is not None
        window._show_integrations()
        app.processEvents()
        dialog = window._utility_dialogs[-1]
        assert isinstance(dialog, QDialog)
        assert dialog.screen().availableGeometry().contains(dialog.geometry())
        scroll_areas = dialog.findChildren(QScrollArea)
        assert scroll_areas
        assert any(area.verticalScrollBar().maximum() > 0 for area in scroll_areas)
        close = next(btn for btn in dialog.findChildren(QPushButton) if btn.text() == "Fechar")
        assert close.isVisible()
        dialog.close()
        dialog.deleteLater()
        window._utility_dialogs.clear()
    finally:
        window.close()
        window.deleteLater()
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_custom_municipal_source_renders_and_updates_in_settings(tmp_path) -> None:
    """UI smoke without monkeypatching C++ Qt methods or spawning a second worker."""
    pytest.importorskip("PySide6")

    from imobhunter.application.custom_municipal_sources import CustomMunicipalStore
    from imobhunter.sources.custom_municipal import reload_custom_sources
    from imobhunter.sources.registry import build_default_registry
    from imobhunter.ui_settings import SourceSettingsDialog

    store = CustomMunicipalStore(tmp_path / "municipal_sources")
    source = store.add(
        "Geoportal da prefeitura", "Bertioga", "SP",
        "https://portal.bertioga.sp.gov.br/geoserver/ows", "wfs",
    )
    registry = build_default_registry()
    source_id = source.source_id
    app = _app()
    dialog = SourceSettingsDialog(registry, custom_store=store)
    dialog.show()
    app.processEvents()
    try:
        assert source_id in dialog._municipal_probe_buttons
        assert source_id in dialog._municipal_probe_labels
        assert "Não testada" in dialog._municipal_probe_labels[source_id].text()
        assert any(
            field.text() == source.url
            for field in dialog.findChildren(type(dialog.geosampa_url))
        )
        file = tmp_path / "lotes.csv"
        file.write_text("logradouro;numero;quadra;lote\nRua A;100;01;02\n", encoding="utf-8")
        saved, count = store.import_file(source_id, file)
        assert count == 1 and saved.file_name.endswith(".csv")
        reload_custom_sources(registry, store)
        dialog._refresh_custom_sources()
        app.processEvents()
        assert registry.get(source_id).status().status == "configured"
        assert any(
            field.text() == source.url
            for field in dialog.findChildren(type(dialog.geosampa_url))
        )
        assert store.remove(source_id)
        reload_custom_sources(registry, store)
        dialog._refresh_custom_sources()
        app.processEvents()
        assert registry.get(source_id) is None
        assert source_id not in dialog._municipal_probe_buttons
        assert file.exists()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_bertioga_candidate_details_on_native_map(monkeypatch) -> None:
    """Public parcel attributes remain explicitly tied to a candidate, not address SQL."""
    pytest.importorskip("PySide6")
    import json

    from imobhunter.domain.models import PropertyRecord
    from imobhunter.ui_cadastral_map import CadastralMapWidget

    monkeypatch.setattr(CadastralMapWidget, "_request_visible_tiles", lambda self: None)
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [[[[-46.10, -23.82], [-46.099, -23.82],
                          [-46.099, -23.819], [-46.10, -23.82]]]],
    }
    record = PropertyRecord(
        city="Bertioga", state="SP", address="Rua Exemplo, 177",
        block="4", lot="6",
        attributes={
            "geometry_geojson": json.dumps(geometry),
            "cadastre_match": "spatial_candidate_only",
            "inscricao_cadastral_do_lote_candidato": "16.004.022.000",
            "matricula_informada_no_lote": "2/55391",
            "zoneamento_candidato": [{"code": "ZM1", "label": "ZM1 - Zona Mista"}],
            "sql": None, "iptu_registration_number": None,
        },
    )
    app = _app()
    widget = CadastralMapWidget([record])
    widget.show()
    app.processEvents()
    try:
        assert widget._target is not None
        assert widget.features[0].classification == "candidate"
        details = widget.details.toPlainText()
        assert "Inscrição publicada no lote candidato" in details
        assert "16.004.022.000" in details
        assert "Matrícula publicada no lote candidato" in details
        assert "2/55391" in details
        assert "Zoneamento indicativo do lote" in details
        assert "ZM1 - Zona Mista" in details
        assert "Não fornecido nesta fonte" in details
        assert "Número predial confirmado" not in details
    finally:
        widget.close()
        app.processEvents()
