"""Optional offscreen Qt smoke test (runs when desktop dependencies are present).

No network requests are made. CI without the optional desktop extra skips this
test instead of installing heavyweight Qt just to validate pure data logic.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_map_has_selectable_parcels_and_changes_real_zoom(monkeypatch) -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

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
    app = QApplication.instance() or QApplication([])
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
