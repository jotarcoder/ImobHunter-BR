from __future__ import annotations

from html import escape
from concurrent.futures import ThreadPoolExecutor
import math
import httpx
from pathlib import Path
import sys
import uuid
from urllib.parse import quote

from PySide6.QtCore import QThreadPool, QObject, QRunnable, QUrl, Qt, Signal, Slot, QPointF, QTimer
from PySide6.QtGui import QBrush, QColor, QCursor, QDesktopServices, QFont, QIcon, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QGraphicsView,
    QGraphicsPolygonItem,
    QGraphicsEllipseItem,
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .application.coverage import DDDCoverageRegistry, load_ddd_coverage
from .application.search import SearchResult, SearchService
from .application.export import export_search_result_csv, export_search_result_json
from .domain.models import SearchRequest
import json
from .ui_market import MarketIntelligenceDialog
from .ui_settings import SourceSettingsDialog


APP_STYLE = """
QMainWindow, QWidget { background:#07111b; color:#eaf2f7; font-family:"Segoe UI"; }
QFrame#sidebar { background:#091722; border-right:1px solid #183044; }
QFrame#card { background:#0c1926; border:1px solid #1b3348; border-radius:16px; }
QFrame#hero { background:linear-gradient(145deg,#0d1d2d,#0a1724); border:1px solid #214058; border-radius:20px; }
QLabel#brand { font-size:20px; font-weight:800; color:#f4f8fb; }
QLabel#muted { color:#7f96a9; font-size:12px; }
QLabel#title { font-size:31px; font-weight:800; color:#f4f8fb; }
QLabel#section { font-size:14px; font-weight:750; color:#dce8ef; }
QLabel#metric { font-size:24px; font-weight:800; color:#f4f8fb; }
QLabel#resultTitle { font-size:18px; font-weight:800; color:#f4f8fb; }
QLineEdit { background:#07131f; border:1px solid #20384d; border-radius:11px; padding:11px 13px; color:#f4f8fb; selection-background-color:#236a47; }
QLineEdit:hover { border-color:#31536d; }
QLineEdit:focus { border:1px solid #35ff77; background:#081622; }
QPushButton { background:#101f2e; border:1px solid #234057; border-radius:10px; padding:9px 13px; color:#e9f1f5; font-weight:650; }
QPushButton:hover { background:#162b3d; border-color:#37627c; }
QPushButton:pressed { background:#0d1b28; }
QPushButton:disabled { color:#536a7b; background:#0d1822; border-color:#182b3a; }
QPushButton#primary { background:#35ff77; border:1px solid #35ff77; color:#04110a; padding:11px 18px; border-radius:11px; font-weight:800; }
QPushButton#primary:hover { background:#5aff91; }
QPushButton#nav { text-align:left; padding:11px 12px; border:0; background:transparent; color:#8da2b2; border-radius:9px; }
QPushButton#nav:hover { background:#102332; color:#f1f7fa; }
QPushButton#nav:checked { background:#123325; color:#65ff98; border-left:2px solid #35ff77; }
QPushButton#ddd { padding:7px 12px; border-radius:9px; background:#0c1a27; border:1px solid #1d354a; min-width:72px; }
QPushButton#ddd:hover { background:#13283a; border-color:#35ff77; color:#f4fff7; }
QScrollArea { border:0; background:transparent; }
QProgressBar { background:#17293a; border:0; border-radius:4px; height:7px; }
QProgressBar::chunk { background:#35ff77; border-radius:4px; }
"""



class SearchWorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class SearchWorker(QRunnable):
    def __init__(self, service: SearchService, request: SearchRequest) -> None:
        super().__init__()
        self.service = service
        self.request = request
        self.signals = SearchWorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.finished.emit(self.service.search(self.request))
        except Exception as exc:  # noqa: BLE001 - prevent adapter/database failures from killing the UI worker.
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")



class IntegrationProbeSignals(QObject):
    finished = Signal(str, str, str, int)


class IntegrationProbeWorker(QRunnable):
    def __init__(self, source, request: SearchRequest) -> None:
        super().__init__()
        self.source = source
        self.request = request
        self.signals = IntegrationProbeSignals()

    @Slot()
    def run(self) -> None:
        import time
        started = time.monotonic()
        state = "error"
        message = "A fonte não retornou um estado."
        try:
            status = self.source.status()
            if status.status == "not_configured":
                state = "not_configured"
                message = status.message or "Fonte não configurada."
            else:
                records = self.source.search(self.request)
                if records:
                    state = "ok"
                    message = f"Consulta respondida com {len(records)} registro(s)."
                else:
                    state = "no_results"
                    message = "A fonte respondeu, mas não encontrou registros para esta consulta."
        except Exception as exc:  # noqa: BLE001 - each adapter is isolated.
            state = "error"
            message = f"{type(exc).__name__}: {exc}"
        elapsed_ms = int((time.monotonic() - started) * 1000)
        self.signals.finished.emit(self.source.source_id, state, message, elapsed_ms)


class MetricCard(QFrame):
    def __init__(self, label: str, value: str = "—") -> None:
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(3)
        label_widget = QLabel(label)
        label_widget.setObjectName("muted")
        self.value = QLabel(value)
        self.value.setObjectName("metric")
        layout.addWidget(label_widget)
        layout.addWidget(self.value)

    def set_value(self, value: str) -> None:
        self.value.setText(value)



class InteractiveMapView(QGraphicsView):
    """Graphics map with mouse-wheel zoom and hand-drag panning."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if not delta:
            event.ignore()
            return
        self.scale(1.2 if delta > 0 else 1 / 1.2, 1.2 if delta > 0 else 1 / 1.2)
        event.accept()


class CadastralMapDialog(QDialog):
    """Interactive cadastral map with a clear highlight for the exact matched parcel."""

    def __init__(self, records, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mapa do imóvel — ruas e cadastro")
        self.resize(1080, 760)
        self.setMinimumSize(760, 560)
        self._records = list(records)
        self.setStyleSheet(
            "QDialog { background:#07111b; color:#eaf2f7; } "
            "QLabel { color:#dce8ef; } "
            "QPushButton { background:#102131; border:1px solid #2a465b; "
            "border-radius:9px; padding:8px 13px; color:#eaf2f7; font-weight:650; } "
            "QPushButton:hover { border-color:#35ff77; background:#153044; } "
            "QTextBrowser { background:#0c1926; border:1px solid #1b3348; "
            "border-radius:10px; padding:10px; color:#eaf2f7; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QVBoxLayout()
        title = QLabel("Imóvel localizado")
        title.setStyleSheet("font-size:22px; font-weight:800; color:#f4f8fb;")
        header.addWidget(title)
        self.hint = QLabel(
            "A parcela confirmada será destacada em verde e circulada em vermelho."
        )
        self.hint.setStyleSheet("color:#91a8b8; font-size:12px;")
        header.addWidget(self.hint)
        layout.addLayout(header)

        toolbar = QHBoxLayout()
        self.zoom_out_button = QPushButton("−  Zoom")
        self.zoom_out_button.setToolTip("Afastar o mapa")
        self.zoom_out_button.clicked.connect(lambda: self.view.scale(0.8, 0.8))
        toolbar.addWidget(self.zoom_out_button)
        self.zoom_in_button = QPushButton("+  Zoom")
        self.zoom_in_button.setToolTip("Aproximar o mapa")
        self.zoom_in_button.clicked.connect(lambda: self.view.scale(1.25, 1.25))
        toolbar.addWidget(self.zoom_in_button)
        self.fit_button = QPushButton("Enquadrar lotes")
        self.fit_button.clicked.connect(self._fit_map)
        toolbar.addWidget(self.fit_button)
        toolbar.addStretch(1)
        street_button = QPushButton("Ver ruas no OpenStreetMap ↗")
        street_button.setToolTip("Abre a busca de endereço no mapa de ruas; não altera os dados cadastrais.")
        street_button.clicked.connect(self._open_street_map)
        toolbar.addWidget(street_button)
        official_button = QPushButton("Abrir novo GeoSampa ↗")
        official_button.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://novogeosampa.prefeitura.sp.gov.br/")
            )
        )
        official_button.setVisible(any(
            provenance.source_id == "geosampa"
            for record in self._records
            for provenance in record.provenance
        ))
        toolbar.addWidget(official_button)
        layout.addLayout(toolbar)

        self.view = InteractiveMapView()
        self.view.setObjectName("cadastralMapView")
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setBackgroundBrush(QBrush(QColor("#091722")))
        self.view.setStyleSheet("QGraphicsView { border:1px solid #1b3348; border-radius:12px; }")
        self.scene = QGraphicsScene(self)
        self.view.setScene(self.scene)
        layout.addWidget(self.view, 1)

        legend = QHBoxLayout()
        swatch = QLabel("●")
        swatch.setStyleSheet("color:#35ff77; font-size:18px;")
        legend.addWidget(swatch)
        legend.addWidget(QLabel("Lote cadastral"))
        ring = QLabel("◉")
        ring.setStyleSheet("color:#ff5d67; font-size:18px;")
        legend.addWidget(ring)
        legend.addWidget(QLabel("Imóvel do endereço pesquisado"))
        legend.addWidget(QLabel("Ruas e mapa base: © OpenStreetMap contributors"))
        legend.addStretch(1)
        layout.addLayout(legend)

        self.details = QTextBrowser()
        self.details.setMaximumHeight(150)
        layout.addWidget(self.details)

        geometries = []
        point_records = []
        all_lon_lat = []
        for record in records:
            try:
                geometry = json.loads(record.attributes.get("geometry_geojson") or "null")
            except (TypeError, ValueError):
                geometry = None
            if geometry and geometry.get("type") in {"Polygon", "MultiPolygon"}:
                geometries.append((record, geometry))
                polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
                for polygon in polygons:
                    for ring in polygon:
                        all_lon_lat.extend(
                            (float(point[0]), float(point[1]))
                            for point in ring if isinstance(point, list) and len(point) >= 2
                        )
            elif record.latitude is not None and record.longitude is not None:
                point_records.append(record)
                all_lon_lat.append((float(record.longitude), float(record.latitude)))

        if not all_lon_lat:
            self.hint.setText("A fonte não retornou coordenadas nem geometria para mapear.")
            self.details.setPlainText(
                "O dossiê continua disponível, mas nenhuma fonte forneceu coordenadas utilizáveis."
            )
            for button in (self.zoom_out_button, self.zoom_in_button, self.fit_button):
                button.setEnabled(False)
            return

        target = next(
            (record for record, _geometry in geometries
             if record.attributes.get("house_number_match") == "exact"),
            None,
        )
        if target is None:
            target = next(
                (record for record in point_records
                 if record.attributes.get("record_kind") == "geocoded_address_only"),
                None,
            )
        if geometries:
            if target is not None:
                self.hint.setText("Lotes oficiais recebidos da fonte. O endereço exato está destacado quando confirmado.")
            else:
                self.hint.setText("Lotes candidatos retornados pela fonte. Confira os dados de cada polígono.")
        else:
            self.hint.setText(
                "Localização geocodificada. A fonte não forneceu lote oficial, SQL/IPTU ou área cadastral."
            )

        center_lon = (min(point[0] for point in all_lon_lat) + max(point[0] for point in all_lon_lat)) / 2
        center_lat = (min(point[1] for point in all_lon_lat) + max(point[1] for point in all_lon_lat)) / 2
        zoom = 17
        tile_x, tile_y = self._mercator_tile(center_lon, center_lat, zoom)
        tile_x0, tile_y0 = math.floor(tile_x) - 1, math.floor(tile_y) - 1
        self._tile_zoom = zoom
        self._tile_origin = (tile_x0, tile_y0)

        # Load a small, cached 3x3 street-tile viewport only when the user opens
        # the map. This is not a bulk download; local cache avoids repeat traffic.
        tile_cache = Path.home() / ".imobhunter" / "map-tiles"
        tile_cache.mkdir(parents=True, exist_ok=True)
        tile_specs = [
            (x, y, tile_cache / f"{zoom}_{x}_{y}.png")
            for x in range(tile_x0, tile_x0 + 3)
            for y in range(tile_y0, tile_y0 + 3)
        ]

        def load_tile(spec):
            x, y, path = spec
            if not path.exists():
                try:
                    response = httpx.get(
                        f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png",
                        headers={"User-Agent": "ImobHunter-BR/0.1 (desktop map view)"},
                        timeout=2.5,
                    )
                    response.raise_for_status()
                    if response.headers.get("content-type", "").startswith("image/"):
                        path.write_bytes(response.content)
                except (httpx.HTTPError, OSError):
                    return x, y, None
            image = QImage(str(path))
            return x, y, image if not image.isNull() else None

        basemap = QImage(768, 768, QImage.Format.Format_ARGB32)
        basemap.fill(QColor("#091722"))
        painter = QPainter(basemap)
        with ThreadPoolExecutor(max_workers=4) as executor:
            for x, y, image in executor.map(load_tile, tile_specs):
                if image is not None:
                    painter.drawImage((x - tile_x0) * 256, (y - tile_y0) * 256, image)
        painter.end()
        basemap_item = QGraphicsPixmapItem(QPixmap.fromImage(basemap))
        basemap_item.setZValue(-10)
        basemap_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.scene.addItem(basemap_item)

        def to_scene(lon, lat):
            x, y = self._mercator_tile(float(lon), float(lat), zoom)
            return ((x - tile_x0) * 256, (y - tile_y0) * 256)

        for record, geometry in geometries:
            is_target = record is target
            polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
            for polygon in polygons:
                if not polygon or not polygon[0]:
                    continue
                points = [to_scene(point[0], point[1]) for point in polygon[0] if len(point) >= 2]
                if len(points) < 3:
                    continue
                item = QGraphicsPolygonItem(QPolygonF([QPointF(x, y) for x, y in points]))
                item.setBrush(QBrush(QColor("#35ff77" if is_target else "#174456")))
                item.setPen(QPen(QColor("#ff5d67" if is_target else "#64869a"), 3.5 if is_target else 1.2))
                item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, True)
                item.setData(0, record)
                item.setData(1, is_target)
                item.setZValue(2 if is_target else 1)
                item.setToolTip(
                    f"Quadra {record.block or '—'} · Lote {record.lot or '—'}"
                    + (" · ENDEREÇO EXATO" if is_target else "")
                )
                self.scene.addItem(item)

        for record in point_records:
            x, y = to_scene(record.longitude, record.latitude)
            marker = QGraphicsEllipseItem(x - 7, y - 7, 14, 14)
            marker.setBrush(QBrush(QColor("#35ff77")))
            marker.setPen(QPen(QColor("#ff5d67"), 3))
            marker.setFlag(marker.GraphicsItemFlag.ItemIsSelectable, True)
            marker.setData(0, record)
            marker.setData(1, True)
            marker.setZValue(5)
            marker.setToolTip("Localização geocodificada — não representa limite cadastral")
            self.scene.addItem(marker)

        self.scene.setSceneRect(0, 0, 768, 768)
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.scene.selectionChanged.connect(self._show_selection)
        if target is not None:
            for item in self.scene.items():
                if item.data(0) is target and item.flags() & item.GraphicsItemFlag.ItemIsSelectable:
                    item.setSelected(True)
                    break
        else:
            for item in self.scene.items():
                if isinstance(item, QGraphicsPolygonItem):
                    item.setSelected(True)
                    break

    @staticmethod
    def _mercator_tile(longitude, latitude, zoom):
        latitude = max(-85.05112878, min(85.05112878, float(latitude)))
        n = 2 ** zoom
        x = (float(longitude) + 180.0) / 360.0 * n
        lat_rad = math.radians(latitude)
        y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
        return x, y

    def _open_street_map(self):
        records = getattr(self, "_records", [])
        target = next((r for r in records if r.attributes.get("house_number_match") == "exact"), records[0] if records else None)
        if target is None:
            QDesktopServices.openUrl(QUrl("https://www.openstreetmap.org/"))
            return
        address = ", ".join(str(v) for v in (target.address, target.city, target.state, "Brasil") if v)
        QDesktopServices.openUrl(QUrl("https://www.openstreetmap.org/search?query=" + quote(address, safe="")))

    def _fit_map(self):
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _show_selection(self):
        selected = [
            item for item in self.scene.selectedItems()
            if isinstance(item, QGraphicsPolygonItem)
            or (isinstance(item, QGraphicsEllipseItem) and item.data(0) is not None)
        ]
        if not selected:
            return
        record = selected[0].data(0)
        attributes = dict(record.attributes)
        attributes.pop("geometry_geojson", None)
        attributes.pop("source_attributes", None)
        attributes.pop("source_attribute_names", None)
        area = (
            f"{record.area_m2:g} m²"
            if record.area_m2 is not None
            else "Não informada"
        )
        lines = [
            f"<b>Endereço:</b> {escape(record.address or 'Não informado')}",
            f"<b>SQL/IPTU:</b> {escape(str(record.property_id or 'Não informado'))}",
            (
                f"<b>Quadra fiscal:</b> {escape(str(record.block or '—'))} · "
                f"<b>Lote:</b> {escape(str(record.lot or '—'))}"
            ),
            f"<b>Área do terreno:</b> {escape(area)}",
            "<b>Atributos fornecidos pela fonte:</b><br>"
            + "<br>".join(
                f"{escape(str(key))}: {escape(str(value))}"
                for key, value in attributes.items()
                if value not in (None, "")
            ),
        ]
        self.details.setHtml("<br>".join(lines))



class SearchResultsWindow(QMainWindow):
    """Independent, minimizable results window for one property search."""

    def __init__(self, request: SearchRequest) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        address = " ".join(part for part in (request.address, request.number) if part)
        location = ", ".join(part for part in (request.city, request.state) if part)
        query = address or f"Quadra {request.block}, lote {request.lot}" if request.block else (request.cib or address)
        self.setWindowTitle(f"ImobHunter-BR • {query} • {location}".strip(" •"))
        self.resize(1120, 820)
        self.setMinimumSize(760, 560)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)
        header = QLabel("Dossiê da pesquisa")
        header.setObjectName("title")
        subtitle = QLabel(f"{query}  ·  {location}\nEsta janela é independente. Você pode minimizá-la e continuar pesquisando na tela principal.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        layout.addWidget(header)
        layout.addWidget(subtitle)
        self.summary = QLabel("Consultando fontes…")
        self.summary.setObjectName("section")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self._completed = False
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._show_timeout)
        self._watchdog.start(90000)
        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(True)
        self.details.setStyleSheet(
            "QTextBrowser { background:#0c1926; border:1px solid #1b3348; "
            "border-radius:12px; padding:16px; color:#eaf2f7; font-size:13px; }"
        )
        layout.addWidget(self.details, 1)
        actions = QHBoxLayout()
        self._result: SearchResult | None = None
        self.export_csv_button = QPushButton("Exportar CSV")
        self.export_csv_button.setEnabled(False)
        self.export_csv_button.clicked.connect(self._export_csv)
        actions.addWidget(self.export_csv_button)
        self.export_json_button = QPushButton("Exportar JSON")
        self.export_json_button.setEnabled(False)
        self.export_json_button.clicked.connect(self._export_json)
        actions.addWidget(self.export_json_button)
        self.map_button = QPushButton("Mapa cadastral dos lotes")
        self.map_button.setEnabled(False)
        self.map_button.clicked.connect(self._open_cadastral_map)
        actions.addWidget(self.map_button)
        map_button = QPushButton("Abrir GeoSampa oficial ↗")
        map_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://geosampa.prefeitura.sp.gov.br/"))
        )
        actions.addWidget(map_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.setCentralWidget(root)

    def _show_timeout(self) -> None:
        if self._completed:
            return
        self._completed = True
        self.summary.setText("Tempo limite excedido. Uma ou mais fontes não finalizaram a consulta.")
        self.details.setPlainText(
            "A consulta ultrapassou 90 segundos. Feche esta janela ou continue usando a tela principal. "
            "Confira as integrações e tente novamente; esta mensagem não significa que o imóvel não exista."
        )

    def _export_csv(self) -> None:
        if self._result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar dossiê em CSV", "imobhunter-dossie.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            export_search_result_csv(self._result, Path(path))
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Exportação CSV", f"Não foi possível exportar o arquivo: {exc}")
            return
        self.summary.setText(f"Exportação CSV concluída: {path}")

    def _export_json(self) -> None:
        if self._result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar dossiê em JSON", "imobhunter-dossie.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            export_search_result_json(self._result, Path(path))
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Exportação JSON", f"Não foi possível exportar o arquivo: {exc}")
            return
        self.summary.setText(f"Exportação JSON concluída: {path}")

    def _open_cadastral_map(self) -> None:
        records = getattr(self, "_map_records", [])
        dialog = CadastralMapDialog(records, self)
        dialog.exec()

    def set_result(self, result: SearchResult) -> None:
        self._result = result
        self.export_csv_button.setEnabled(True)
        self.export_json_button.setEnabled(True)
        self._completed = True
        self._watchdog.stop()
        self._map_records = [r for r in result.records if r.attributes.get("geometry_geojson")]
        self.map_button.setEnabled(bool(self._map_records))
        sources = result.sources
        found = len(result.records)
        self.summary.setText(
            f"{found} registro(s) · {len(result.dossiers)} dossiê(s) consolidado(s) · "
            f"{sum(s.status in {'ok', 'no_results'} for s in sources)} fonte(s) responderam"
        )
        parts = []
        for i, dossier in enumerate(result.dossiers, 1):
            parts.append(f"<h2>Imóvel {i} — confiança {dossier.score:.0f}/100</h2>")
            parts.append("<p>" + escape(" • ".join(dossier.score_reasons) or "Sem indicadores suficientes.") + "</p>")
            parts.append("<table width='100%' cellspacing='0' cellpadding='8'>")
            for fact in dossier.facts:
                parts.append(
                    "<tr><td width='34%' bgcolor='#122536'><b>" + escape(str(fact.field).replace("attribute:", "").replace("_", " ").capitalize()) +
                    "</b></td><td>" + escape(str(fact.value)) +
                    "<br><small>Fonte: " + escape(str(fact.provenance.source_id)) +
                    " · Confiança: " + f"{fact.provenance.confidence:.0%}" + "</small></td></tr>"
                )
            parts.append("</table>")
            if dossier.conflicts:
                parts.append("<h3 style='color:#ffcc66'>Divergências entre fontes</h3><ul>")
                for conflict in dossier.conflicts:
                    parts.append("<li>" + escape(str(conflict.field)) + ": " + escape(" ↔ ".join(str(v) for v in conflict.values)) + "</li>")
                parts.append("</ul>")
        if not result.dossiers:
            parts.append(
                "<p><b>Nenhum dossiê consolidado.</b> Isso não confirma que o imóvel não exista. "
                "Confira cobertura, endereço e mensagens das fontes.</p>"
            )
        parts.append("<h2>Diagnóstico das fontes</h2><table width='100%' cellspacing='0' cellpadding='8'>")
        for source in sources:
            parts.append(
                "<tr><td width='30%'><b>" + escape(str(source.name)) + "</b></td><td>" +
                escape(str(source.status)) + " · " + escape(str(source.records_count)) +
                " registro(s)<br>" + escape(str(source.message or "Sem mensagem adicional.")) + "</td></tr>"
            )
        parts.append("</table>")
        self.details.setHtml("".join(parts))

    def set_error(self, message: str) -> None:
        self._completed = True
        self._watchdog.stop()
        self.summary.setText("A pesquisa não pôde ser concluída.")
        self.details.setPlainText(message)


class MainWindow(QMainWindow):
    def __init__(self, service: SearchService, coverage: DDDCoverageRegistry) -> None:
        super().__init__()
        self.service = service
        self.coverage = coverage
        self.thread_pool = QThreadPool.globalInstance()
        self._result_windows: list[SearchResultsWindow] = []
        self.setWindowTitle("ImobHunter-BR")
        logo_path = Path(__file__).resolve().parent / "assets" / "logo.svg"
        self.setWindowIcon(QIcon(str(logo_path)))
        cursor_path = Path(__file__).resolve().parent / "assets" / "magnetic_cursor.svg"
        cursor_pixmap = QPixmap(str(cursor_path)).scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._magnetic_cursor = QCursor(cursor_pixmap, 4, 3)
        self.setCursor(self._magnetic_cursor)
        self.resize(1320, 820)
        self.setMinimumSize(980, 680)
        self._build()
        for button in self.findChildren(QPushButton):
            button.setCursor(self._magnetic_cursor)
        for field in self.findChildren(QLineEdit):
            field.setCursor(Qt.CursorShape.IBeamCursor)
        self._populate_coverage()

    def _build(self) -> None:
        root = QWidget()
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(218)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 22, 18, 18)
        side.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_icon = QLabel()
        brand_icon.setPixmap(QPixmap(str(Path(__file__).resolve().parent / "assets" / "logo.svg")).scaled(34, 34, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        brand_row.addWidget(brand_icon)
        brand = QLabel("ImobHunter")
        brand.setObjectName("brand")
        brand_row.addWidget(brand)
        brand_row.addStretch()
        side.addLayout(brand_row)
        subtitle = QLabel("Inteligência imobiliária")
        subtitle.setObjectName("muted")
        side.addWidget(subtitle)
        side.addSpacing(20)
        self.nav_prospect = QPushButton("⌕  Prospecção")
        self.nav_prospect.setObjectName("nav")
        self.nav_prospect.setCheckable(True)
        self.nav_prospect.setChecked(True)
        self.nav_prospect.clicked.connect(lambda: self.address.setFocus())
        side.addWidget(self.nav_prospect)

        self.nav_coverage = QPushButton("▦  Cobertura")
        self.nav_coverage.setObjectName("nav")
        self.nav_coverage.clicked.connect(self._focus_coverage)
        side.addWidget(self.nav_coverage)

        self.nav_market = QPushButton("⌖  Inteligência de Mercado")
        self.nav_market.setObjectName("nav")
        self.nav_market.clicked.connect(self._show_market_intelligence)
        side.addWidget(self.nav_market)

        self.nav_sources = QPushButton("◈  Fontes")
        self.nav_sources.setObjectName("nav")
        self.nav_sources.clicked.connect(self._show_sources)
        side.addWidget(self.nav_sources)

        self.nav_integrations = QPushButton("⟳  Integrações")
        self.nav_integrations.setObjectName("nav")
        self.nav_integrations.clicked.connect(self._show_integrations)
        side.addWidget(self.nav_integrations)

        self.nav_settings = QPushButton("⚙  Configurações")
        self.nav_settings.setObjectName("nav")
        self.nav_settings.clicked.connect(self._show_settings)
        side.addWidget(self.nav_settings)

        downloads = QPushButton("↓  Downloads e políticas")
        downloads.setObjectName("nav")
        downloads.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/jotarcoder/ImobHunter-BR/releases")))
        side.addWidget(downloads)
        side.addStretch()
        local = QLabel("●  Processamento local\n   Dados pesados permanecem no PC")
        local.setStyleSheet("color:#6ee89a;font-size:11px;font-weight:650;")
        side.addWidget(local)
        shell.addWidget(sidebar)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Caçando oportunidades.")
        title.setObjectName("title")
        title_box.addWidget(title)
        caption = QLabel("Pesquisa multi-fonte com processamento pesado no seu PC.")
        caption.setObjectName("muted")
        title_box.addWidget(caption)
        header.addLayout(title_box)
        header.addStretch()
        status = QLabel("●  LOCAL-FIRST")
        status.setStyleSheet(
            "background:#12271e;color:#76d9a0;border:1px solid #1e4c36;"
            "padding:7px 10px;border-radius:9px;font-weight:700;font-size:11px;"
        )
        header.addWidget(status, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        hero = QFrame()
        hero.setObjectName("hero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(20, 18, 20, 20)
        hero_layout.setSpacing(12)

        section = QLabel("Pesquisar imóvel")
        section.setObjectName("section")
        hero_layout.addWidget(section)

        row = QHBoxLayout()
        self.address = QLineEdit()
        self.address.setPlaceholderText("Rua, avenida ou endereço completo")
        self.number = QLineEdit()
        self.number.setPlaceholderText("Nº")
        self.number.setMaximumWidth(100)
        self.city = QLineEdit()
        self.city.setPlaceholderText("Cidade")
        self.city.setMaximumWidth(190)
        self.state = QLineEdit()
        self.state.setPlaceholderText("UF")
        self.state.setMaximumWidth(72)
        self.search_button = QPushButton("Pesquisar imóvel  →")
        self.search_button.setObjectName("primary")
        self.search_button.clicked.connect(self._search)
        row.addWidget(self.address, 1)
        row.addWidget(self.number)
        row.addWidget(self.search_button)
        hero_layout.addLayout(row)

        location_row = QHBoxLayout()
        location_row.setSpacing(10)
        self.city.setMaximumWidth(420)
        self.state.setMaximumWidth(100)
        location_row.addWidget(self.city, 1)
        location_row.addWidget(self.state)
        location_row.addStretch(1)
        hero_layout.addLayout(location_row)

        parcel_row = QHBoxLayout()
        self.block = QLineEdit()
        self.block.setPlaceholderText("Quadra (opcional)")
        self.block.setMaximumWidth(190)
        self.lot = QLineEdit()
        self.lot.setPlaceholderText("Lote (opcional)")
        self.lot.setMaximumWidth(150)
        self.block.setMaximumWidth(150)
        self.cib = QLineEdit()
        self.cib.setPlaceholderText("Código CIB (opcional)")
        self.cib.setMaximumWidth(180)
        parcel_hint = QLabel("Endereço, quadra+lote ou CIB.")
        parcel_hint.setObjectName("muted")
        parcel_row.addWidget(self.block)
        parcel_row.addWidget(self.lot)
        parcel_row.addWidget(self.cib)
        parcel_row.addWidget(parcel_hint, 1)
        hero_layout.addLayout(parcel_row)

        self.search_status = QLabel("Endereço + número ou quadra + lote.")
        self.search_status.setObjectName("muted")
        hero_layout.addWidget(self.search_status)
        layout.addWidget(hero)

        coverage_header = QHBoxLayout()
        coverage_title = QLabel("Cobertura por DDD")
        coverage_title.setObjectName("section")
        coverage_header.addWidget(coverage_title)
        coverage_header.addStretch()
        coverage_hint = QLabel("Selecione uma região para preparar a pesquisa")
        coverage_hint.setObjectName("muted")
        coverage_header.addWidget(coverage_hint)
        layout.addLayout(coverage_header)

        self.coverage_scroll = QScrollArea()
        self.coverage_scroll.setWidgetResizable(True)
        self.coverage_scroll.setMinimumHeight(104)
        self.coverage_scroll.setMaximumHeight(132)
        self.coverage_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.coverage_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        coverage_host = QWidget()
        self.coverage_layout = QVBoxLayout(coverage_host)
        self.coverage_layout.setContentsMargins(0, 0, 0, 0)
        self.coverage_layout.setSpacing(7)
        self.coverage_scroll.setWidget(coverage_host)
        layout.addWidget(self.coverage_scroll)

        metrics = QHBoxLayout()
        self.metric_properties = MetricCard("IMÓVEIS ENCONTRADOS")
        self.metric_sources = MetricCard("FONTES CONSULTADAS")
        self.metric_confidence = MetricCard("CONFIANÇA MÉDIA")
        self.metric_region = MetricCard("REGIÃO ATIVA")
        for card in (
            self.metric_properties,
            self.metric_sources,
            self.metric_confidence,
            self.metric_region,
        ):
            metrics.addWidget(card)
        layout.addLayout(metrics)

        results = QFrame()
        results.setObjectName("card")
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(18, 16, 18, 16)
        results_title = QLabel("Resultado da pesquisa")
        results_title.setObjectName("resultTitle")
        results_layout.addWidget(results_title)
        self.dossier_scroll = QScrollArea()
        self.dossier_scroll.setWidgetResizable(True)
        self.dossier_host = QWidget()
        self.dossier_layout = QVBoxLayout(self.dossier_host)
        self.dossier_layout.setContentsMargins(0, 4, 0, 0)
        self.dossier_layout.setSpacing(10)
        self.dossier_scroll.setWidget(self.dossier_host)
        self.dossier_scroll.setMinimumHeight(240)
        self.dossier_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.dossier_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        results_layout.addWidget(self.dossier_scroll, 1)
        self.result_text = QLabel(
            "Pronto para pesquisar. O ImobHunter consulta as fontes configuradas "
            "e consolida os registros sem enviar os dados pesados para o servidor."
        )
        self.result_text.setObjectName("muted")
        self.result_text.setWordWrap(True)
        results_layout.addWidget(self.result_text)
        results.hide()  # Os resultados completos ficam em janelas independentes.

        root.setLayout(shell)
        shell.addWidget(content, 1)
        self.setCentralWidget(root)

    def _show_market_intelligence(self) -> None:
        dialog = MarketIntelligenceDialog(self)
        dialog.exec()

    def _focus_coverage(self) -> None:
        # Bring the actual DDD controls into keyboard focus and provide visible feedback.
        first_button = self.coverage_scroll.widget().findChild(QPushButton, "ddd")
        if first_button is not None:
            self.coverage_scroll.ensureWidgetVisible(first_button)
            first_button.setFocus(Qt.FocusReason.OtherFocusReason)
        self.search_status.setText(
            f"Cobertura carregada: {len(self.coverage.all())} DDDs cadastrados. "
            "Clique em um DDD para selecionar a região."
        )
        self.metric_region.set_value("Selecione um DDD")

    def _show_integrations(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Painel de integrações")
        dialog.resize(980, 760)
        dialog.setMinimumSize(760, 560)
        root = QVBoxLayout(dialog)
        title = QLabel("Diagnóstico das integrações")
        title.setObjectName("title")
        root.addWidget(title)
        intro = QLabel(
            "Teste cada adaptador com os dados atuais da pesquisa. As consultas rodam em segundo plano; "
            "um timeout é sinalizado separadamente de uma falha e de uma resposta sem resultados. "
            "A cobertura geográfica e os dados disponíveis dependem de cada fonte."
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        root.addWidget(intro)

        table = QTextBrowser()
        table.setOpenExternalLinks(True)
        table.setStyleSheet(
            "QTextBrowser { background:#0c1926; border:1px solid #1b3348; "
            "border-radius:12px; padding:14px; color:#eaf2f7; font-size:13px; }"
        )
        parts = ["<h2>Estado de configuração</h2><table width='100%' cellspacing='0' cellpadding='8'>"]
        sources = self.service.registry.all()
        for source in sources:
            try:
                status = source.status()
                state = {
                    "available": "Registrada; ainda não testada",
                    "ok": "Conectada",
                    "not_configured": "Não configurada",
                    "error": "Erro de configuração",
                }.get(status.status, status.status)
                message = status.message or "Sem detalhes fornecidos pelo adaptador."
            except Exception as exc:  # noqa: BLE001
                state = "Falha ao consultar estado"
                message = f"{type(exc).__name__}: {exc}"
            parts.append(
                "<tr><td width='26%'><b>" + escape(source.name) + "</b><br><small>" +
                escape(source.source_id) + "</small></td><td><b>" + escape(state) +
                "</b><br>" + escape(message) + "</td></tr>"
            )
        parts.append("</table>")
        table.setHtml("".join(parts))
        root.addWidget(table, 1)

        request_box = QLabel("Consulta de teste: use endereço + cidade + UF, quadra + lote + cidade + UF ou código CIB preenchidos na tela principal.")
        request_box.setWordWrap(True)
        root.addWidget(request_box)

        status_labels = {}
        buttons = {}
        for source in sources:
            row = QHBoxLayout()
            label = QLabel(f"{source.name} ({source.source_id}) — aguardando teste")
            label.setWordWrap(True)
            row.addWidget(label, 1)
            button = QPushButton("Testar conexão")
            button.clicked.connect(
                lambda checked=False, s=source, l=label, b=button: self._test_integration(s, l, b, dialog)
            )
            row.addWidget(button)
            root.addLayout(row)
            status_labels[source.source_id] = label
            buttons[source.source_id] = button

        links = QLabel(
            "<a href='https://geosampa.prefeitura.sp.gov.br/'>GeoSampa oficial</a> · "
            "<a href='https://www.ibge.gov.br/'>IBGE</a> · "
            "<a href='https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/dados-abertos/cadastros'>Dados abertos CNPJ</a>"
        )
        links.setOpenExternalLinks(True)
        root.addWidget(links)
        close_button = QPushButton("Fechar")
        close_button.setObjectName("primary")
        close_button.clicked.connect(dialog.accept)
        root.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    def _test_integration(self, source, label: QLabel, button: QPushButton, dialog: QDialog) -> None:
        address = self.address.text().strip() or None
        number = self.number.text().strip() or None
        city = self.city.text().strip() or None
        state = self.state.text().strip().upper() or None
        block = self.block.text().strip() or None
        lot = self.lot.text().strip() or None
        cib = self.cib.text().strip() or None
        request = SearchRequest(
            address=address, number=number, city=city, state=state,
            block=block, lot=lot, cib=cib,
        )
        try:
            request.validate()
            if (address and (not city or not state or len(state) != 2)) or (
                (block or lot) and (not block or not lot or not city or not state or len(state) != 2)
            ):
                raise ValueError("Preencha cidade e UF (2 letras) para endereço ou quadra/lote.")
        except ValueError as exc:
            QMessageBox.information(self, "Consulta de teste incompleta", str(exc))
            return

        token = uuid.uuid4().hex
        button.setProperty("probe_token", token)
        button.setProperty("probe_timed_out", False)
        button.setEnabled(False)
        label.setText(f"{source.name} — testando…")
        worker = IntegrationProbeWorker(source, request)
        worker.signals.finished.connect(
            lambda source_id, result, message, elapsed, s=source, l=label, b=button, t=token:
                self._integration_probe_finished(source_id, result, message, elapsed, s, l, b, t)
        )
        timer = QTimer(dialog)
        timer.setSingleShot(True)
        timer.timeout.connect(
            lambda s=source, l=label, b=button, t=token:
                self._integration_probe_timeout(s, l, b, t)
        )
        button._integration_probe_timer = timer
        timer.start(12000)
        self._integration_probe_timers = getattr(self, "_integration_probe_timers", [])
        self._integration_probe_timers.append(timer)
        self._integration_probe_workers = getattr(self, "_integration_probe_workers", [])
        self._integration_probe_workers.append(worker)
        self.thread_pool.start(worker)

    def _integration_probe_timeout(self, source, label: QLabel, button: QPushButton, token: int) -> None:
        if button.property("probe_token") != token:
            return
        button.setProperty("probe_timed_out", True)
        button.setEnabled(True)
        label.setText(f"{source.name} — TIMEOUT: mais de 12 segundos. A consulta pode ainda estar em execução.")

    def _integration_probe_finished(
        self, source_id: str, result: str, message: str, elapsed_ms: int,
        source, label: QLabel, button: QPushButton, token: int,
    ) -> None:
        if button.property("probe_token") != token:
            return
        if button.property("probe_timed_out"):
            return
        timer = getattr(button, "_integration_probe_timer", None)
        if timer is not None:
            timer.stop()
        button.setEnabled(True)
        labels = {
            "ok": "CONECTADA · com resultados",
            "no_results": "RESPONDEU · sem resultados",
            "not_configured": "NÃO CONFIGURADA",
            "error": "FALHA",
        }
        label.setText(
            f"{source.name} — {labels.get(result, result.upper())} · {elapsed_ms} ms · {message}"
        )


    def _show_sources(self) -> None:
        lines = ["Fontes registradas no aplicativo:", ""]
        for source in self.service.registry.all():
            try:
                status = source.status()
                label = {
                    "available": "Disponível",
                    "ok": "Disponível",
                    "not_configured": "Não configurada",
                    "error": "Erro de configuração",
                }.get(status.status, status.status)
                lines.append(f"• {source.name}: {label}")
                if status.message:
                    lines.append(f"  {status.message}")
            except (OSError, RuntimeError, ValueError, TypeError) as exc:
                lines.append(f"• {source.name}: falha ao verificar status ({exc})")
            lines.append("")
        lines.append(
            "A presença na lista não garante que a fonte tenha dados para todo endereço. "
            "A pesquisa mostra os resultados e falhas de cada fonte."
        )
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Fontes de dados")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText("\n".join(lines))
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.exec()

    def _show_settings(self) -> None:
        dialog = SourceSettingsDialog(self.service.registry, self)
        if dialog.exec():
            self.search_status.setText(
                "Configurações aplicadas. As próximas pesquisas usarão as fontes atualizadas."
            )
            self._show_sources()

    def _populate_coverage(self) -> None:
        for project in self.coverage.all():
            button = QPushButton(f"{project.ddd} • {project.label}")
            button.setObjectName("ddd")
            button.clicked.connect(lambda checked=False, p=project: self._select_ddd(p))
            self.coverage_layout.addWidget(button)
        self.coverage_layout.addStretch()

    def _select_ddd(self, project) -> None:
        self.metric_region.set_value(project.label)
        self.search_status.setText(
            f"DDD {project.ddd} selecionado • {', '.join(project.states)}"
        )

    def _search(self) -> None:
        address = self.address.text().strip()
        number = self.number.text().strip() or None
        city = self.city.text().strip()
        state = self.state.text().strip().upper()
        block = self.block.text().strip() or None
        lot = self.lot.text().strip() or None
        cib = self.cib.text().strip() or None
        has_address = bool(address and city and len(state) == 2)
        has_parcel = bool(block and lot and city and len(state) == 2)
        has_cib = bool(cib)
        if not (has_address or has_parcel or has_cib):
            QMessageBox.warning(
                self,
                "Dados incompletos",
                "Informe endereço + cidade + UF, quadra + lote + cidade + UF, ou um código CIB.",
            )
            return
        if bool(block) != bool(lot):
            QMessageBox.warning(
                self,
                "Identificação incompleta",
                "Para pesquisar por cadastro fiscal, preencha quadra e lote.",
            )
            return

        request = SearchRequest(
            address=address,
            number=number,
            city=city,
            state=state,
            block=block,
            lot=lot,
            cib=cib,
        )
        result_window = SearchResultsWindow(request)
        self._result_windows.append(result_window)
        result_window.show()
        result_window.raise_()
        result_window.activateWindow()
        self.search_button.setEnabled(False)
        self._active_search_window = result_window
        self._search_watchdog = QTimer(self)
        self._search_watchdog.setSingleShot(True)
        self._search_watchdog.timeout.connect(self._search_timeout)
        self._search_watchdog.start(90000)
        self.search_status.setText("Consultando fontes configuradas… A tela principal continua disponível.")
        worker = SearchWorker(self.service, request)
        worker.signals.finished.connect(lambda result, w=result_window: self._search_finished_in_window(w, result))
        worker.signals.failed.connect(lambda message, w=result_window: self._search_failed_in_window(w, message))
        self.thread_pool.start(worker)


    def _search_timeout(self) -> None:
        self.search_button.setEnabled(True)
        self.search_status.setText("Tempo limite da pesquisa excedido. Você já pode iniciar outra consulta.")
        window = getattr(self, "_active_search_window", None)
        if window is not None:
            window._show_timeout()

    def _search_finished_in_window(self, window: SearchResultsWindow, result: SearchResult) -> None:
        if hasattr(self, "_search_watchdog"):
            self._search_watchdog.stop()
        self.search_button.setEnabled(True)
        self.search_status.setText("Pesquisa concluída. Você pode iniciar outra pesquisa sem fechar esta janela.")
        window.set_result(result)

    def _search_failed_in_window(self, window: SearchResultsWindow, message: str) -> None:
        if hasattr(self, "_search_watchdog"):
            self._search_watchdog.stop()
        self.search_button.setEnabled(True)
        self.search_status.setText("A pesquisa falhou. Os detalhes estão na janela desta pesquisa.")
        window.set_error(message)

    def _search_finished(self, result: SearchResult) -> None:
        self.search_button.setEnabled(True)
        sources = result.sources
        self._last_search_sources = sources
        found = len(result.records)
        active = sum(source.status in {"ok", "no_results"} for source in sources)
        self.metric_properties.set_value(str(found))
        self.metric_sources.set_value(str(active))
        if result.dossiers:
            score = sum(dossier.score for dossier in result.dossiers) / len(result.dossiers)
            self.metric_confidence.set_value(f"{score:.0f}/100")
        else:
            self.metric_confidence.set_value("—")
        self.search_status.setText("Pesquisa concluída sem bloquear a interface.")
        self.result_text.setText(
            f"{found} registro(s) encontrado(s) em {active} fonte(s). "
            f"{len(result.dossiers)} imóvel(is) consolidado(s) após reconciliação."
        )
        self._render_dossiers(result.dossiers)


    def _render_dossiers(self, dossiers) -> None:
        while self.dossier_layout.count():
            item = self.dossier_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not dossiers:
            message = QLabel(
                "Nenhum dossiê foi consolidado. Isso não significa necessariamente que o endereço "
                "não exista: as fontes podem não cobrir a cidade, não ter dados para esse número "
                "ou ter falhado durante a consulta."
            )
            message.setWordWrap(True)
            self.dossier_layout.addWidget(message)
            for source in getattr(self, "_last_search_sources", ()):
                detail = QLabel(
                    f"{source.name} — {source.status}: "
                    f"{source.message or (str(source.records_count) + ' registro(s)')}"
                )
                detail.setWordWrap(True)
                detail.setObjectName("muted")
                self.dossier_layout.addWidget(detail)
            return
        for index, dossier in enumerate(dossiers, 1):
            card = QFrame()
            card.setObjectName("card")
            box = QVBoxLayout(card)
            title = QLabel(f"Imóvel {index}  •  confiança {dossier.score:.0f}/100")
            title.setObjectName("resultTitle")
            box.addWidget(title)
            reasons = QLabel(" • ".join(dossier.score_reasons) or "Sem indicadores suficientes.")
            reasons.setObjectName("muted")
            reasons.setWordWrap(True)
            box.addWidget(reasons)
            preview = QLabel(self._dossier_preview(dossier))
            preview.setWordWrap(True)
            box.addWidget(preview)
            details = QPushButton("Abrir dossiê completo  →")
            details.clicked.connect(lambda checked=False, d=dossier: self._show_dossier(d))
            box.addWidget(details)
            for fact in dossier.facts:
                label = QLabel(
                    f"<b>{fact.field}</b>: {fact.value}  ·  "
                    f"fonte: {fact.provenance.source_id}  · "
                    f"confiança: {fact.provenance.confidence:.0%}"
                )
                label.setTextFormat(Qt.TextFormat.RichText)
                label.setWordWrap(True)
                box.addWidget(label)
            if dossier.conflicts:
                conflict = QLabel("Conflitos: " + " | ".join(
                    f"{item.field}: " + " ↔ ".join(str(value) for value in item.values)
                    for item in dossier.conflicts
                ))
                conflict.setWordWrap(True)
                conflict.setStyleSheet("color:#ffcc66;")
                box.addWidget(conflict)
            self.dossier_layout.addWidget(card)
        self.dossier_layout.addStretch()


    @staticmethod
    def _dossier_preview(dossier) -> str:
        important = {"address", "area_m2", "cib", "property_id", "block", "lot"}
        values = [
            f"{fact.field}: {fact.value}"
            for fact in dossier.facts
            if fact.field in important
        ]
        return "  •  ".join(values) or "Identificação detalhada disponível no dossiê."

    def _show_dossier(self, dossier) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Dossiê do imóvel")
        dialog.resize(820, 680)
        dialog.setMinimumSize(620, 480)
        root = QVBoxLayout(dialog)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)
        header = QFrame()
        header.setObjectName("hero")
        header_layout = QVBoxLayout(header)
        title = QLabel("Dossiê do imóvel")
        title.setObjectName("title")
        subtitle = QLabel(f"Confiabilidade dos dados: {dossier.score:.0f}/100 · {len(dossier.facts)} informações consolidadas")
        subtitle.setObjectName("muted")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        root.addWidget(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 2, 8, 2)
        content_layout.setSpacing(12)
        registry_fact = next((fact for fact in dossier.facts if fact.field == "registry_number"), None)
        registry_value = escape(str(registry_fact.value)) if registry_fact else "Não localizada nas fontes consultadas — isso não significa que não exista."
        registry = QLabel("<b>Matrícula:</b> " + registry_value)
        registry.setWordWrap(True)
        registry.setObjectName("muted")
        content_layout.addWidget(registry)
        labels = {
            "address": "Endereço", "area_m2": "Área do terreno (m²)", "cib": "CIB",
            "property_id": "Identificador cadastral", "block": "Quadra fiscal", "lot": "Lote fiscal",
            "attribute:sql": "Número de inscrição IPTU / SQL",
            "attribute:iptu_registration_number": "Número de inscrição IPTU / SQL",
            "attribute:iptu_contributor": "Nome do contribuinte IPTU",
            "attribute:taxpayer_name": "Nome do contribuinte IPTU",
            "attribute:iptu_reference_year": "Ano de referência do IPTU",
            "attribute:iptu_data_scope": "Período da base IPTU",
            "attribute:iptu_current_debt_status": "Situação dos débitos atuais",
            "attribute:built_area_m2": "Área construída (m²)", "attribute:door_number": "Número predial",
            "attribute:sector": "Setor fiscal", "attribute:condominium": "Condomínio",
            "attribute:lot_status": "Situação do lote", "attribute:lot_type": "Tipo de lote",
        }
        shown_iptu_registration = False
        shown_taxpayer_name = False
        for fact in dossier.facts:
            if fact.field == "registry_number":
                continue
            if fact.field in {"attribute:sql", "attribute:iptu_registration_number"}:
                if shown_iptu_registration:
                    continue
                shown_iptu_registration = True
            if fact.field in {"attribute:iptu_contributor", "attribute:taxpayer_name"}:
                if shown_taxpayer_name:
                    continue
                shown_taxpayer_name = True
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            if fact.field.startswith("source_attribute:"):
                _, source_id, source_field = fact.field.split(":", 2)
                raw_label = (
                    f"{source_id.replace('_', ' ').title()} · "
                    f"{source_field.replace('_', ' ')}"
                )
            else:
                raw_label = labels.get(
                    fact.field,
                    fact.field.replace("attribute:", "").replace("_", " ").capitalize(),
                )
            label = QLabel(escape(raw_label))
            label.setObjectName("muted")
            value = QLabel(escape(str(fact.value)))
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setWordWrap(True)
            value.setStyleSheet("font-size:16px;font-weight:700;color:#f4f8fb;")
            source = QLabel(f"Fonte: {escape(fact.provenance.source_id)} · Confiança: {fact.provenance.confidence:.0%}")
            source.setObjectName("muted")
            card_layout.addWidget(label)
            card_layout.addWidget(value)
            card_layout.addWidget(source)
            content_layout.addWidget(card)
        if not shown_taxpayer_name:
            note = QLabel(
                "Nome do contribuinte IPTU não foi fornecido pela fonte consultada. "
                "O SQL identifica o cadastro fiscal, mas não é o nome do contribuinte. "
                "A base histórica disponível pode não refletir a situação atual."
            )
            note.setWordWrap(True)
            note.setStyleSheet("color:#ffcc66;")
            content_layout.addWidget(note)
        if dossier.conflicts:
            conflict_card = QFrame()
            conflict_card.setObjectName("card")
            conflict_layout = QVBoxLayout(conflict_card)
            conflict_title = QLabel("Divergências entre fontes")
            conflict_title.setObjectName("section")
            conflict_layout.addWidget(conflict_title)
            for conflict in dossier.conflicts:
                label = QLabel(f"{escape(str(conflict.field))}: " + " ↔ ".join(escape(str(value)) for value in conflict.values))
                label.setWordWrap(True)
                conflict_layout.addWidget(label)
            content_layout.addWidget(conflict_card)
        content_layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        actions = QHBoxLayout()
        actions.addStretch()
        lookup_button = QPushButton("Consultar RI Digital")
        lookup_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://ridigital.org.br/")))
        close_button = QPushButton("Fechar")
        close_button.setObjectName("primary")
        close_button.clicked.connect(dialog.accept)
        actions.addWidget(lookup_button)
        actions.addWidget(close_button)
        root.addLayout(actions)
        dialog.exec()

    def _search_failed(self, message: str) -> None:
        self.search_button.setEnabled(True)
        self.search_status.setText("A pesquisa não pôde ser concluída.")
        QMessageBox.warning(self, "Pesquisa", message)


def build_window(service: SearchService, coverage: DDDCoverageRegistry) -> MainWindow:
    return MainWindow(service, coverage)


def resource_path(relative: str) -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / relative
    return Path(__file__).resolve().parents[1] / relative


def coverage_from_project_root() -> DDDCoverageRegistry:
    return load_ddd_coverage(resource_path("data/coverage/ddd.json"))


def apply_style(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    app.setFont(QFont("Segoe UI", 10))
