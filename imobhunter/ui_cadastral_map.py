"""Native Qt cadastral map: dynamic street tiles and official parcel overlays.

The map is part of the dossier (no modal dialog, no WebEngine or CDN required).
Street tiles load in bounded background workers as the viewport moves. Parcel
polygons come exclusively from the returned GeoJSON, not from OSM street tiles.
"""
from __future__ import annotations

from html import escape
import math
import os
from pathlib import Path

import httpx
from PySide6.QtCore import QObject, QPointF, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .application.cadastral_map import (
    CLASSIFICATION_LABELS,
    CadastralFeature,
    feature_points,
    map_center,
    prepare_features,
    preferred_target,
    sql_from_source,
)
from .domain.models import PropertyRecord, SearchRequest

TILE_SIZE = 256
MIN_ZOOM = 11
MAX_ZOOM = 19
MAX_TILES_PER_VIEW = 36
MAX_CONCURRENT_TILES = 3
TILE_URL = "https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
CACHE_DIR = Path.home() / ".imobhunter" / "map-tiles"

_MAP_TILE_POOL: QThreadPool | None = None


def _map_tile_pool() -> QThreadPool:
    """A single QApplication-owned pool lives longer than individual map tabs.

    Do not hold a Python reference to QThreadPool.globalInstance(): some Qt
    bindings can destruct that shared QObject during interpreter shutdown.
    """
    global _MAP_TILE_POOL
    if _MAP_TILE_POOL is None:
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("A QApplication deve existir antes do mapa.")
        _MAP_TILE_POOL = QThreadPool(app)
        _MAP_TILE_POOL.setMaxThreadCount(MAX_CONCURRENT_TILES)
    return _MAP_TILE_POOL


COLORS = {
    "exact": ("#35ff77", "#deffea"),
    "parcel_query_match": ("#43ed82", "#dbffe9"),
    "spatial_match": ("#92ed6e", "#f7edb5"),
    "candidate": ("#eda944", "#fff2d0"),
    "neighbor": ("#48564e", "#b3bfb5"),
    "unverified": ("#51675a", "#9ab5a3"),
}


def to_pixels(longitude: float, latitude: float, zoom: int) -> QPointF:
    lat = max(-85.05112878, min(85.05112878, latitude))
    factor = TILE_SIZE * 2**zoom
    x = (longitude + 180.0) / 360.0 * factor
    y = (
        1 - math.asinh(math.tan(math.radians(lat))) / math.pi
    ) / 2 * factor
    return QPointF(x, y)


def from_pixels(x: float, y: float, zoom: int) -> tuple[float, float]:
    factor = TILE_SIZE * 2**zoom
    lon = (x / factor) * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / factor))))
    return lon, lat


class MapViewport(QGraphicsView):
    viewport_changed = Signal()
    zoom_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor("#0d1711")))
        self.setStyleSheet("QGraphicsView { border:1px solid #294733; border-radius:9px; }")

    def wheelEvent(self, event) -> None:
        steps = event.angleDelta().y()
        if steps:
            # Change geographic zoom, not bitmap scale. Tiles and polygons
            # are reprojected at the new resolution.
            self.zoom_requested.emit(1 if steps > 0 else -1)
            event.accept()
        else:
            super().wheelEvent(event)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self.viewport_changed.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.viewport_changed.emit()


class TileSignals(QObject):
    finished = Signal(int, int, int, object)


class TileWorker(QRunnable):
    """Only fetch one explicitly visible street tile; never prefetch neighborhoods."""

    def __init__(self, zoom: int, x: int, y: int) -> None:
        super().__init__()
        self.zoom, self.x, self.y = zoom, x, y
        self.signals = TileSignals()
        self.cancelled = False

    def run(self) -> None:
        if self.cancelled:
            self.signals.finished.emit(self.zoom, self.x, self.y, b"")
            return
        data = b""
        path = CACHE_DIR / str(self.zoom) / str(self.x) / f"{self.y}.png"
        try:
            if path.is_file():
                data = path.read_bytes()
            if not data:
                response = httpx.get(
                    TILE_URL.format(zoom=self.zoom, x=self.x, y=self.y),
                    timeout=httpx.Timeout(4.0, connect=3.0),
                    headers={
                        "User-Agent": (
                            "ImobHunter-BR/2.0 (desktop cadastral viewer; "
                            "https://imobhunter-br.pages.dev/)"
                        ),
                    },
                    follow_redirects=False,
                )
                response.raise_for_status()
                if (
                    response.headers.get("content-type", "").startswith("image/png")
                    and len(response.content) <= 1_000_000
                    and response.content.startswith(b"\x89PNG\r\n\x1a\n")
                ):
                    data = response.content
                    try:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        temporary = path.with_suffix(".part")
                        temporary.write_bytes(data)
                        os.replace(temporary, path)
                    except OSError:
                        pass  # Map still renders when a cache folder is read-only.
        except (OSError, httpx.HTTPError):
            pass  # Offline? Leave basemap blank; never drop cadastral parcels.
        self.signals.finished.emit(self.zoom, self.x, self.y, data)


class CadastralMapWidget(QWidget):
    """Scrollable native map, with selectable official lots and source-aware details."""

    def __init__(
        self, records: list[PropertyRecord], parent=None, request: SearchRequest | None = None
    ) -> None:
        super().__init__(parent)
        self.features = prepare_features(records, request)
        self._target = preferred_target(self.features)
        self._zoom = 17
        self._loaded_tiles: dict[tuple[int, int, int], QGraphicsPixmapItem] = {}
        self._pending_tiles: dict[tuple[int, int, int], TileWorker] = {}
        self._failed_tiles: set[tuple[int, int, int]] = set()
        self._displayed_record: PropertyRecord | None = None
        # QApplication owns this pool: closing a map cannot synchronously
        # destroy a worker thread pool while an HTTP tile request is active.
        self._workers = _map_tile_pool()
        self._refresh = QTimer(self)
        self._refresh.setSingleShot(True)
        self._refresh.setInterval(200)
        self._refresh.timeout.connect(self._request_visible_tiles)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(5, 8, 5, 5)
        outer.setSpacing(9)

        controls = QHBoxLayout()
        minus = QPushButton("−")
        minus.setToolTip("Afastar mapa: buscar ruas na resolução correta")
        minus.clicked.connect(lambda: self._change_zoom(-1))
        controls.addWidget(minus)
        plus = QPushButton("+")
        plus.setToolTip("Aproximar mapa: buscar ruas na resolução correta")
        plus.clicked.connect(lambda: self._change_zoom(1))
        controls.addWidget(plus)
        reload_button = QPushButton("Recarregar ruas")
        reload_button.setToolTip("Tentar novamente tiles temporariamente indisponíveis")
        reload_button.clicked.connect(self._retry_tiles)
        controls.addWidget(reload_button)
        fit_button = QPushButton("Enquadrar lotes")
        fit_button.clicked.connect(self._fit_features)
        controls.addWidget(fit_button)
        center_button = QPushButton("Centralizar imóvel")
        center_button.clicked.connect(self._center_target)
        controls.addWidget(center_button)
        controls.addStretch(1)
        osm_button = QPushButton("Abrir ruas no OpenStreetMap ↗")
        osm_button.clicked.connect(self._open_osm)
        controls.addWidget(osm_button)
        outer.addLayout(controls)

        status = QLabel()
        status.setWordWrap(True)
        status.setStyleSheet("color:#b8d0bc; font-size:12px;")
        self.status = status
        outer.addWidget(status)
        legend = QLabel(
            "<span style='color:#35ff77'>■</span> Confirmado pelo número/quadra/lote  ·  "
            "<span style='color:#92ed6e'>■</span> Correspondência espacial  ·  "
            "<span style='color:#eda944'>■</span> Candidato  ·  "
            "<span style='color:#a0aaa2'>■</span> Vizinho / não confirmado"
        )
        legend.setWordWrap(True)
        outer.addWidget(legend)

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.scene = QGraphicsScene(self)
        self.view = MapViewport(self)
        self.view.setObjectName("cadastralMapView")
        self.view.setScene(self.scene)
        self.view.zoom_requested.connect(self._change_zoom)
        self.view.viewport_changed.connect(self._schedule_tiles)
        splitter.addWidget(self.view)

        details_container = QWidget()
        details_layout = QVBoxLayout(details_container)
        details_layout.setContentsMargins(0, 4, 0, 0)
        details_header = QHBoxLayout()
        details_header.addWidget(QLabel("Dados do lote selecionado"))
        details_header.addStretch(1)
        copy_button = QPushButton("Copiar dados")
        copy_button.clicked.connect(self._copy_details)
        details_header.addWidget(copy_button)
        details_layout.addLayout(details_header)
        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(False)
        self.details.setStyleSheet(
            "QTextBrowser { background:#101b13; color:#edf8ef; "
            "border:1px solid #31543a; border-radius:9px; }"
        )
        details_layout.addWidget(self.details)
        splitter.addWidget(details_container)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter, 1)
        footer = QLabel(
            "Ruas: © OpenStreetMap contributors · Polígonos: somente fontes "
            "cadastrais consultadas · A geocodificação não prova titularidade, SQL ou lote."
        )
        footer.setWordWrap(True)
        footer.setStyleSheet("color:#849a88;font-size:11px")
        outer.addWidget(footer)

        self.scene.selectionChanged.connect(self._selection_changed)
        polygons = sum(f.has_official_polygon for f in self.features)
        if not self.features:
            self.status.setText(
                "Nenhuma coordenada WGS84 ou geometria válida foi recebida. "
                "Os dados do dossiê continuam disponíveis."
            )
            self.details.setPlainText("Nenhum lote ou ponto cartográfico para exibir.")
            minus.setEnabled(False)
            plus.setEnabled(False)
            fit_button.setEnabled(False)
            center_button.setEnabled(False)
            return

        self.status.setText(
            f"{polygons} registro(s) com polígono cadastral retornado · "
            f"{len(self.features) - polygons} localização(ões) pontuais. "
            "Arraste para navegar; use a roda do mouse para aproximar. "
            "Lotes sem confirmação permanecem identificados como candidatos."
        )
        if not polygons:
            self.status.setText(
                "Somente localização pontual: não há geometria oficial de lote "
                "para delinear nesta consulta. Você pode navegar pelas ruas."
            )
        self._rebuild(self._zoom, map_center(self.features))
        if self._target is None:
            self.details.setPlainText(
                "Clique num lote ou marcador para consultar os dados retornados. "
                "Nenhum polígono foi confirmado como o endereço pesquisado."
            )
        else:
            self._display_feature(self._target)

    def _rebuild(self, zoom: int, center: tuple[float, float] | None) -> None:
        for key, worker in list(self._pending_tiles.items()):
            if key[0] != zoom:
                worker.cancelled = True
                self._pending_tiles.pop(key, None)
        self._zoom = zoom
        self._loaded_tiles.clear()
        self.scene.clear()
        self.view.resetTransform()
        world = TILE_SIZE * 2**zoom
        self.scene.setSceneRect(0, 0, world, world)
        for feature in self.features:
            fill, border = COLORS[feature.classification]
            is_target = feature is self._target
            for polygon in feature.polygons:
                path = QPainterPath()
                path.setFillRule(Qt.FillRule.OddEvenFill)
                for ring in polygon:
                    if len(ring) < 3:
                        continue
                    first = to_pixels(*ring[0], zoom)
                    path.moveTo(first)
                    for lon, lat in ring[1:]:
                        path.lineTo(to_pixels(lon, lat, zoom))
                    path.closeSubpath()
                if path.isEmpty():
                    continue
                item = QGraphicsPathItem(path)
                paint = QColor(fill)
                paint.setAlpha(125 if is_target else 85)
                item.setBrush(QBrush(paint))
                item.setPen(QPen(QColor(border), 3.5 if is_target else 1.5))
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
                item.setData(0, feature)
                item.setToolTip(self._tooltip(feature))
                item.setZValue(10 if is_target else 5)
                self.scene.addItem(item)
            if not feature.polygons and feature.point:
                pos = to_pixels(*feature.point, zoom)
                marker = QGraphicsEllipseItem(
                    pos.x() - 7, pos.y() - 7, 14, 14
                )
                marker.setBrush(QBrush(QColor(fill)))
                marker.setPen(QPen(QColor(border), 2))
                marker.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
                marker.setData(0, feature)
                marker.setZValue(15)
                marker.setToolTip(self._tooltip(feature) + " (ponto, sem limite de lote)")
                self.scene.addItem(marker)
        if center:
            self.view.centerOn(to_pixels(*center, zoom))
        self._schedule_tiles()

    @staticmethod
    def _tooltip(feature: CadastralFeature) -> str:
        rec = feature.record
        return (
            f"{CLASSIFICATION_LABELS[feature.classification]} · "
            f"Quadra {rec.block or 'não informada'} · "
            f"Lote {rec.lot or 'não informado'}"
        )

    def _change_zoom(self, delta: int) -> None:
        new_zoom = min(MAX_ZOOM, max(MIN_ZOOM, self._zoom + delta))
        if new_zoom == self._zoom:
            return
        middle = self.view.mapToScene(self.view.viewport().rect().center())
        center = from_pixels(middle.x(), middle.y(), self._zoom)
        self._rebuild(new_zoom, center)

    def _center_target(self) -> None:
        center = map_center(self.features)
        if center:
            self.view.centerOn(to_pixels(*center, self._zoom))
            self._schedule_tiles()

    def _fit_features(self) -> None:
        all_points = tuple(p for feature in self.features for p in feature_points(feature))
        if not all_points:
            return
        center = (
            (min(p[0] for p in all_points) + max(p[0] for p in all_points)) / 2,
            (min(p[1] for p in all_points) + max(p[1] for p in all_points)) / 2,
        )
        zoom = MIN_ZOOM
        size = self.view.viewport().size()
        for candidate in range(MAX_ZOOM, MIN_ZOOM - 1, -1):
            projected = [to_pixels(*point, candidate) for point in all_points]
            width = max(p.x() for p in projected) - min(p.x() for p in projected)
            height = max(p.y() for p in projected) - min(p.y() for p in projected)
            if width <= max(250, size.width() - 130) and height <= max(230, size.height() - 130):
                zoom = candidate
                break
        self._rebuild(zoom, center)

    def _retry_tiles(self) -> None:
        self._failed_tiles.clear()
        self._schedule_tiles()

    def _schedule_tiles(self) -> None:
        if self.features:
            self._refresh.start()

    def _request_visible_tiles(self) -> None:
        if not self.features or not self.isVisible():
            return
        rect = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        world_tiles = 2**self._zoom
        left = max(0, math.floor(rect.left() / TILE_SIZE) - 1)
        right = min(world_tiles - 1, math.floor(rect.right() / TILE_SIZE) + 1)
        top = max(0, math.floor(rect.top() / TILE_SIZE) - 1)
        bottom = min(world_tiles - 1, math.floor(rect.bottom() / TILE_SIZE) + 1)
        visible = [
            (self._zoom, x, y)
            for x in range(left, right + 1)
            for y in range(top, bottom + 1)
        ]
        middle_x = (rect.left() + rect.right()) / 2 / TILE_SIZE
        middle_y = (rect.top() + rect.bottom()) / 2 / TILE_SIZE
        visible.sort(key=lambda tile: (tile[1] - middle_x)**2 + (tile[2] - middle_y)**2)
        visible = visible[:MAX_TILES_PER_VIEW]
        needed = set(visible)
        for key, item in list(self._loaded_tiles.items()):
            if key not in needed:
                self.scene.removeItem(item)
                del self._loaded_tiles[key]
        for zoom, x, y in visible:
            key = zoom, x, y
            if key in self._loaded_tiles or key in self._pending_tiles or key in self._failed_tiles:
                continue
            # Only three active jobs per map: a closed window cannot leave
            # 36 requests queued and freeze on a pool destructor.
            if len(self._pending_tiles) >= MAX_CONCURRENT_TILES:
                break
            worker = TileWorker(zoom, x, y)
            self._pending_tiles[key] = worker
            worker.signals.finished.connect(self._tile_loaded)
            self._workers.start(worker)

    def _tile_loaded(self, zoom: int, x: int, y: int, data: bytes) -> None:
        key = zoom, x, y
        self._pending_tiles.pop(key, None)
        if zoom != self._zoom or not self.isVisible():
            self._schedule_tiles()
            return
        if not data:
            self._failed_tiles.add(key)
            self._schedule_tiles()
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data, "PNG"):
            self._failed_tiles.add(key)
            self._schedule_tiles()
            return
        if key in self._loaded_tiles:
            return
        item = QGraphicsPixmapItem(pixmap)
        item.setPos(x * TILE_SIZE, y * TILE_SIZE)
        item.setZValue(-100)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.scene.addItem(item)
        self._loaded_tiles[key] = item
        # A viewport pan may have occurred during the asynchronous request.
        self._schedule_tiles()

    def closeEvent(self, event) -> None:
        self._refresh.stop()
        for worker in self._pending_tiles.values():
            worker.cancelled = True
        self._pending_tiles.clear()
        super().closeEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_tiles()

    def _selection_changed(self) -> None:
        selected = [item for item in self.scene.selectedItems() if item.data(0)]
        if selected:
            feature = selected[0].data(0)
            self._display_feature(feature)

    def _display_feature(self, feature: CadastralFeature) -> None:
        rec = feature.record
        self._displayed_record = rec
        category = CLASSIFICATION_LABELS[feature.classification]
        sources = ", ".join(sorted({p.source_id for p in rec.provenance})) or str(
            rec.attributes.get("source") or "Não informada"
        )
        fields = (
            ("Situação", category),
            ("Geometria", "Polígono cadastral retornado pela fonte"
             if feature.has_official_polygon else "Apenas ponto — sem limites cadastrais"),
            ("Endereço informado", rec.address or "Não informado"),
            ("Município/UF", f"{rec.city or '—'}/{rec.state or '—'}"),
            ("SQL / inscrição IPTU", sql_from_source(rec) or "Não fornecido nesta fonte"),
            ("Quadra", rec.block or "Não informada"),
            ("Lote", rec.lot or "Não informado"),
            ("Área do terreno", f"{rec.area_m2:g} m²" if rec.area_m2 is not None
             else "Não informada"),
            ("CIB", rec.cib or "Não informado"),
            ("Matrícula", rec.registry_number or "Não informada"),
            ("Fonte(s)", sources),
        )
        self._details_text = "\n".join(f"{label}: {value}" for label, value in fields)
        self.details.setHtml(
            "<p>" + "<br>".join(
                f"<b>{escape(label)}:</b> {escape(str(value))}" for label, value in fields
            ) + "</p>"
        )

    def _copy_details(self) -> None:
        if self._displayed_record is not None:
            QApplication.clipboard().setText(self._details_text)

    def _open_osm(self) -> None:
        center = map_center(self.features)
        if center:
            lat, lon = center[1], center[0]
            QDesktopServices.openUrl(
                QUrl(f"https://www.openstreetmap.org/#map={self._zoom}/{lat:.6f}/{lon:.6f}")
            )
        else:
            QDesktopServices.openUrl(QUrl("https://www.openstreetmap.org/"))
