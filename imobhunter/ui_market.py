from __future__ import annotations

import csv
import json
from pathlib import Path
from urllib.parse import parse_qs

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QTabWidget, QFrame, QWidget,
)

from .application.market_intelligence import MarketIntelligenceStore
from .application.receita_import import import_receita_archives, search_receita_establishments
from .application.receita_geo import import_receita_coordinates, save_geocoded_establishment
from .application.address_geocoding import CachedAddressGeocoder, GeocodingError
from .application.sidra import fetch_population_estimate, search_municipalities


class _OnlineSearchSignals(QObject):
    finished = Signal(list)
    failed = Signal(str)


class _OnlineSearchWorker(QRunnable):
    def __init__(self, latitude: float, longitude: float, radius_km: float) -> None:
        super().__init__()
        self.latitude = latitude
        self.longitude = longitude
        self.radius_km = radius_km
        self.signals = _OnlineSearchSignals()

    def run(self) -> None:
        try:
            from .application.osm_business_search import fetch_osm_businesses
            places = fetch_osm_businesses(self.latitude, self.longitude, self.radius_km)
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(places)


class _SidraQuerySignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _SidraQueryWorker(QRunnable):
    def __init__(self, query: str) -> None:
        super().__init__()
        self.query = query.strip()
        self.signals = _SidraQuerySignals()

    def run(self) -> None:
        try:
            if self.query.isdigit():
                if len(self.query) != 7:
                    raise ValueError("O código IBGE precisa ter exatamente 7 dígitos.")
                payload = {"kind": "population", "result": fetch_population_estimate(self.query)}
            else:
                payload = {"kind": "municipalities", "items": search_municipalities(self.query)}
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(payload)


class MarketIntelligenceDialog(QDialog):
    """Local-only company and geographic market explorer."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ImobHunter • Inteligência de Mercado")
        self.resize(1280, 820)
        self.setMinimumSize(980, 680)
        data_dir = Path.home() / ".imobhunter" / "market"
        self.store = MarketIntelligenceStore(data_dir / "businesses.sqlite3")
        self._build()
        self._refresh_count()

    def _build(self) -> None:
        self.setStyleSheet("""
            QDialog { background:#07111b; color:#eaf2f7; }
            QLabel { color:#eaf2f7; }
            QLabel#muted { color:#8da2b2; }
            QLineEdit, QComboBox { background:#0b1926; color:#f4f8fb; border:1px solid #254156; border-radius:8px; padding:8px; }
            QPushButton { background:#102332; color:#eaf2f7; border:1px solid #2b4c63; border-radius:9px; padding:9px 12px; }
            QPushButton:hover { border-color:#35ff77; }
            QPushButton#primary { background:#35ff77; color:#04110a; font-weight:800; }
            QTableWidget { background:#091722; alternate-background-color:#0d1d2b; gridline-color:#1b3348; color:#eaf2f7; border:1px solid #1b3348; }
            QHeaderView::section { background:#102332; color:#a9bdcb; padding:7px; border:0; }
        """)
        root = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs)
        self.search_page = QWidget()
        search_layout = QVBoxLayout(self.search_page)
        search_layout.setContentsMargins(12, 12, 12, 12)
        search_layout.setSpacing(10)
        title = QLabel("Inteligência de Mercado")
        title.setStyleSheet("font-size:26px;font-weight:800;color:#f4f8fb")
        search_layout.addWidget(title)
        subtitle = QLabel("Explore empresas por raio e consulte dados econômicos armazenados no seu computador.")
        subtitle.setObjectName("muted")
        search_layout.addWidget(subtitle)

        controls = QHBoxLayout()
        self.latitude = QLineEdit()
        self.latitude.setPlaceholderText("Latitude do ponto central")
        self.longitude = QLineEdit()
        self.longitude.setPlaceholderText("Longitude do ponto central")
        self.radius = QLineEdit("5")
        self.radius.setMaximumWidth(100)
        self.segment = QComboBox()
        self.segment.addItems(["Todos os segmentos", "CNAE contém: comércio", "CNAE contém: serviços", "CNAE contém: indústria", "CNAE contém: construção"])
        controls.addWidget(self.latitude, 1)
        controls.addWidget(self.longitude, 1)
        controls.addWidget(QLabel("Raio (km)"))
        controls.addWidget(self.radius)
        controls.addWidget(self.segment)
        search = QPushButton("Pesquisar região")
        search.setObjectName("primary")
        search.clicked.connect(self._search)
        controls.addWidget(search)
        search_layout.addLayout(controls)

        # Ações em grelha: evita que os rótulos fiquem cortados em ecrãs menores.
        from PySide6.QtWidgets import QGridLayout
        actions = QGridLayout()
        actions.setHorizontalSpacing(8)
        actions.setVerticalSpacing(8)
        geocode_button = QPushButton("Localizar endereço")
        geocode_button.setToolTip("Localiza um endereço e preenche as coordenadas para pesquisar por raio.")
        geocode_button.clicked.connect(self._geocode_address)
        import_button = QPushButton("Importar CSV local")
        import_button.clicked.connect(self._import_csv)
        receita_button = QPushButton("Importar ZIP oficial do CNPJ")
        receita_button.clicked.connect(self._import_receita)
        geo_button = QPushButton("Vincular coordenadas por CNPJ")
        geo_button.clicked.connect(self._import_coordinates)
        browse_button = QPushButton("Consultar base oficial")
        browse_button.clicked.connect(self._browse_receita)
        sidra_button = QPushButton("População IBGE / SIDRA")
        sidra_button.setToolTip("Pesquise pelo nome do município ou informe seu código IBGE para consultar a tabela 6579.")
        sidra_button.clicked.connect(self._query_sidra_population)
        self.sidra_button = sidra_button
        self.online_button = QPushButton("Buscar empresas no mapa")
        self.online_button.setToolTip("Consulta estabelecimentos mapeados no OpenStreetMap dentro do raio informado.")
        self.online_button.setObjectName("primary")
        self.online_button.clicked.connect(self._search_online)
        export_button = QPushButton("Salvar pesquisa…")
        export_button.setToolTip("Salve os resultados em CSV, Excel (.xlsx), JSON ou HTML.")
        export_button.clicked.connect(self._export_results)
        action_buttons = [
            geocode_button, import_button, receita_button, geo_button,
            browse_button, sidra_button, self.online_button, export_button,
        ]
        for index, button in enumerate(action_buttons):
            button.setMinimumHeight(38)
            button.setSizePolicy(button.sizePolicy().Policy.Expanding, button.sizePolicy().Policy.Fixed)
            actions.addWidget(button, index // 4, index % 4)
        search_layout.addLayout(actions)
        self.status = QLabel("Base local pronta. Localize um endereço ou importe dados empresariais para começar.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        search_layout.addWidget(self.status)

        map_title = QLabel("Mapa de calor — concentração de estabelecimentos")
        map_title.setStyleSheet("font-size:17px;font-weight:750;padding-top:6px;")
        search_layout.addWidget(map_title)
        try:
            from PySide6.QtWebEngineCore import QWebEnginePage
            from PySide6.QtWebEngineWidgets import QWebEngineView

            class MapPage(QWebEnginePage):
                map_clicked = Signal(float, float)

                def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
                    if url.scheme() == "imobhunter" and url.host() == "mapclick":
                        query = parse_qs(url.query())
                        try:
                            lat = float(query["lat"][0])
                            lon = float(query["lon"][0])
                            if -90 <= lat <= 90 and -180 <= lon <= 180:
                                self.map_clicked.emit(lat, lon)
                        except (KeyError, ValueError, IndexError):
                            pass
                        return False
                    return super().acceptNavigationRequest(url, navigation_type, is_main_frame)

            self.map_view = QWebEngineView(self)
            self.map_view.setMinimumHeight(250)
            self.map_page = MapPage(self.map_view)
            self.map_page.map_clicked.connect(self._map_clicked)
            self.map_view.setPage(self.map_page)
            search_layout.addWidget(self.map_view, 2)
        except ImportError:
            self.map_view = None
            fallback = QLabel(
                "A visualização cartográfica requer o componente Qt WebEngine desta instalação. "
                "Os resultados e coordenadas continuam disponíveis na tabela."
            )
            fallback.setObjectName("muted")
            fallback.setWordWrap(True)
            search_layout.addWidget(fallback)

        self.table = QTableWidget(0, 8)
        self.table.setMinimumHeight(220)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setHorizontalHeaderLabels([
            "Empresa", "CNPJ", "CNAE", "Endereço", "Distância km",
            "Faturamento divulgado", "Faturamento estimado", "Fonte / atualização"
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        search_layout.addWidget(self.table, 1)
        note = QLabel("Os valores de faturamento só são exibidos quando constam no arquivo importado. Estimativas devem incluir metodologia e fonte; o aplicativo não inventa valores nem consulta o seu servidor.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        search_layout.addWidget(note)
        self.results = []
        self.tabs.addTab(self.search_page, "Pesquisar e mapa")

        self.results_page = QWidget()
        results_layout = QVBoxLayout(self.results_page)
        results_layout.setContentsMargins(16, 16, 16, 16)
        results_layout.setSpacing(12)
        results_title = QLabel("Resultados da pesquisa")
        results_title.setStyleSheet("font-size:24px;font-weight:800;color:#f4f8fb")
        results_layout.addWidget(results_title)
        results_subtitle = QLabel("Tabela pronta para análise e exportação. Os dados e as fontes permanecem identificados.")
        results_subtitle.setObjectName("muted")
        results_subtitle.setWordWrap(True)
        results_layout.addWidget(results_subtitle)

        metrics = QHBoxLayout()
        self.metric_count = self._metric_card("Empresas encontradas", "0")
        self.metric_reported = self._metric_card("Faturamento divulgado", "0")
        self.metric_estimated = self._metric_card("Com estimativa", "0")
        self.metric_radius = self._metric_card("Raio pesquisado", "—")
        for card in (self.metric_count, self.metric_reported, self.metric_estimated, self.metric_radius):
            metrics.addWidget(card, 1)
        results_layout.addLayout(metrics)

        results_actions = QHBoxLayout()
        self.results_status = QLabel("Faça uma pesquisa para preencher esta aba.")
        self.results_status.setObjectName("muted")
        results_actions.addWidget(self.results_status, 1)
        save_results = QPushButton("Exportar / salvar pesquisa…")
        save_results.setObjectName("primary")
        save_results.clicked.connect(self._export_results)
        results_actions.addWidget(save_results)
        results_layout.addLayout(results_actions)

        self.results_table = QTableWidget(0, 8)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.setHorizontalHeaderLabels([
            "Empresa", "CNPJ", "CNAE", "Endereço", "Distância km",
            "Faturamento divulgado", "Faturamento estimado", "Fonte / atualização"
        ])
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSortingEnabled(True)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.verticalHeader().setDefaultSectionSize(32)
        results_layout.addWidget(self.results_table, 1)
        results_note = QLabel("A exportação inclui os registros retornados pela pesquisa, coordenadas disponíveis, origem dos dados e campos de faturamento sem preencher valores ausentes.")
        results_note.setObjectName("muted")
        results_note.setWordWrap(True)
        results_layout.addWidget(results_note)
        self.tabs.addTab(self.results_page, "Resultados e exportação")

    def _refresh_count(self) -> None:
        self.status.setText(f"{self.store.count()} empresa(s) no banco local.")

    def _geocode_address(self) -> None:
        address, accepted = QInputDialog.getText(
            self,
            "Localizar endereço",
            "Digite rua, número, cidade e UF:",
        )
        if not accepted:
            return
        try:
            geocoder = CachedAddressGeocoder(
                self.store.path,
                "ImobHunter-BR/0.1 (aplicativo desktop; contato pelo site institucional)",
            )
            result = geocoder.geocode(address)
        except (GeocodingError, OSError, ValueError) as exc:
            QMessageBox.warning(self, "Geocodificação", str(exc))
            return
        self.latitude.setText(str(result["latitude"]))
        self.longitude.setText(str(result["longitude"]))
        cache_note = " (cache local)" if result.get("cached") else ""
        self.status.setText(
            f"Endereço localizado{cache_note}: {result['display_name']} • {result['attribution']}"
        )
        QMessageBox.information(
            self,
            "Endereço localizado",
            f"{result['display_name']}\n"
            f"Latitude: {result['latitude']}\nLongitude: {result['longitude']}\n\n"
            f"Fonte: {result['provider']} — {result['attribution']}\n"
            "As coordenadas foram preenchidas para a pesquisa por raio. "
            "A consulta é individual e o resultado fica em cache local.",
        )

    def _import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importar base empresarial", "", "CSV (*.csv)")
        if not path:
            return
        try:
            count = self.store.import_csv(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Importação", str(exc))
            return
        self._refresh_count()
        QMessageBox.information(self, "Importação concluída", f"{count} registro(s) válido(s) importado(s) para o banco local.")

    def _import_receita(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Selecionar arquivos ZIP oficiais do CNPJ",
            "", "Arquivos ZIP (*.zip)"
        )
        if not paths:
            return
        try:
            counts = import_receita_archives(self.store.path, paths)
        except (OSError, ValueError, csv.Error) as exc:
            QMessageBox.warning(self, "Importação Receita Federal", str(exc))
            return
        QMessageBox.information(
            self, "Importação concluída",
            "Dados oficiais importados localmente.\n"
            f"Registros de empresas: {counts['companies']:,}\n"
            f"Estabelecimentos: {counts['establishments']:,}\n\n"
            "Observação: os arquivos cadastrais não trazem coordenadas geográficas. "
            "A etapa de geocodificação será necessária para pesquisar por raio."
        )
        self._refresh_count()


    def _import_coordinates(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecionar CSV de coordenadas por CNPJ", "", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            counts = import_receita_coordinates(self.store.path, path)
        except (OSError, ValueError, csv.Error) as exc:
            QMessageBox.warning(self, "Vincular coordenadas", str(exc))
            return
        self._refresh_count()
        QMessageBox.information(
            self, "Vinculação concluída",
            f"Correspondências encontradas: {counts['matched']:,}\\n"
            f"Novas empresas na pesquisa por raio: {counts['inserted']:,}\\n"
            f"Registros atualizados: {counts['updated']:,}\\n"
            f"Linhas ignoradas ou sem CNPJ correspondente: {counts['skipped']:,}\\n\\n"
            "A vinculação usa o CNPJ completo. O CSV precisa conter cnpj, latitude e longitude. "
            "Nenhuma geocodificação em massa foi executada."
        )

    def _browse_receita(self) -> None:
        dialog = ReceitaBrowseDialog(self.store.path, self)
        dialog.exec()

    def _search_online(self) -> None:
        try:
            lat = float(self.latitude.text().strip().replace(",", "."))
            lon = float(self.longitude.text().strip().replace(",", "."))
            radius = float(self.radius.text().strip().replace(",", "."))
            if not (0 < radius <= 25):
                raise ValueError("A busca online aceita raio entre 0 e 25 km.")
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("Coordenadas inválidas. Localize um endereço antes de pesquisar.")
        except ValueError as exc:
            QMessageBox.warning(self, "Busca online de empresas", str(exc))
            return

        self.online_button.setEnabled(False)
        self.status.setText("Consultando OpenStreetMap em segundo plano…")
        self._online_worker = _OnlineSearchWorker(lat, lon, radius)
        self._online_worker.signals.finished.connect(
            lambda places, r=radius: self._online_search_finished(places, r)
        )
        self._online_worker.signals.failed.connect(self._online_search_failed)
        QThreadPool.globalInstance().start(self._online_worker)

    def _online_search_finished(self, places: list[dict], radius: float) -> None:
        try:
            imported = self.store.import_osm_businesses(places)
            self._search()
            count = len(self.results)
            if not places:
                detail = "A fonte não retornou estabelecimentos mapeados para este raio."
            elif count == 0:
                detail = "Os locais retornados não ficaram dentro do raio após a validação."
            else:
                detail = f"{count} empresa(s) no raio de {radius:g} km."
            self.status.setText(
                f"{detail} {imported} novo(s) registro(s) salvo(s) localmente • © OpenStreetMap"
            )
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            self.status.setText("A consulta terminou, mas não foi possível salvar os resultados.")
            QMessageBox.warning(self, "Busca online de empresas", str(exc))
        finally:
            self.online_button.setEnabled(True)

    def _online_search_failed(self, message: str) -> None:
        self.online_button.setEnabled(True)
        self.status.setText("A consulta online falhou; o restante do aplicativo continua disponível.")
        QMessageBox.warning(self, "Busca online de empresas", message)

    def _search(self) -> None:
        try:
            lat = float(self.latitude.text().strip().replace(",", "."))
            lon = float(self.longitude.text().strip().replace(",", "."))
            radius = float(self.radius.text().strip().replace(",", "."))
            segment = ""
            if self.segment.currentIndex() > 0:
                segment = self.segment.currentText().split(": ", 1)[-1]
            self.results = self.store.search_radius(lat, lon, radius, segment)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Pesquisa regional", str(exc))
            return

        self._populate_results_table(self.table)
        self._populate_results_table(self.results_table)
        self._render_heatmap(lat, lon)
        reported_count = sum(item.get("revenue_reported") is not None for item in self.results)
        estimated_count = sum(item.get("revenue_estimate") is not None for item in self.results)
        self.metric_count.findChild(QLabel, "metricValue").setText(f"{len(self.results):,}".replace(",", "."))
        self.metric_reported.findChild(QLabel, "metricValue").setText(str(reported_count))
        self.metric_estimated.findChild(QLabel, "metricValue").setText(str(estimated_count))
        self.metric_radius.findChild(QLabel, "metricValue").setText(f"{radius:g} km")
        summary = f"{len(self.results)} empresa(s) encontrada(s) no raio de {radius:g} km."
        self.status.setText(summary)
        self.results_status.setText(
            f"{summary} Segmento: {segment or 'todos'} · "
            f"{reported_count} com faturamento divulgado · {estimated_count} com estimativa."
        )
        self.tabs.setCurrentWidget(self.results_page)

    def _populate_results_table(self, table: QTableWidget) -> None:
        table.setSortingEnabled(False)
        table.setRowCount(len(self.results))
        for row_index, item in enumerate(self.results):
            values = [
                item.get("name", ""), item.get("cnpj", ""), item.get("cnae", ""),
                item.get("address", ""), f'{item["distance_km"]:.2f}',
                self._money(item.get("revenue_reported")),
                self._money(item.get("revenue_estimate")),
                " • ".join(
                    value for value in (item.get("source", ""), item.get("updated_at", ""))
                    if value
                ),
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if column in (4, 5, 6):
                    cell.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                table.setItem(row_index, column, cell)
        table.setSortingEnabled(True)

    @staticmethod
    def _metric_card(label: str, value: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background:#0b1926; border:1px solid #254156; border-radius:12px; }"
            "QLabel { border:0; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        heading = QLabel(label)
        heading.setObjectName("muted")
        heading.setWordWrap(True)
        number = QLabel(value)
        number.setObjectName("metricValue")
        number.setStyleSheet("font-size:22px;font-weight:800;color:#35ff77;")
        layout.addWidget(heading)
        layout.addWidget(number)
        return card

    def _map_clicked(self, latitude: float, longitude: float) -> None:
        """Recenter the regional search on the point selected on the map."""
        self.latitude.setText(f"{latitude:.6f}")
        self.longitude.setText(f"{longitude:.6f}")
        self._search()

    def _render_heatmap(self, latitude: float, longitude: float) -> None:
        if self.map_view is None:
            return
        points = [
            [float(item["latitude"]), float(item["longitude"]), 0.7]
            for item in self.results
            if item.get("latitude") is not None and item.get("longitude") is not None
        ]
        points_json = json.dumps(points, ensure_ascii=True, separators=(",", ":"))
        center_json = json.dumps([latitude, longitude])
        html = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>html,body,#map{{height:100%;width:100%;margin:0;background:#07111b}}
#note{{position:absolute;z-index:1000;bottom:8px;left:8px;background:#07111be8;color:#eaf2f7;
padding:6px 9px;border-radius:6px;font:12px sans-serif}}</style></head>
<body><div id="map"></div><div id="note">Pontos geolocalizados: <span id="count">0</span> · © OpenStreetMap</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
<script>
const center={center_json}; const points={points_json};
const map=L.map('map').setView(center,13);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
{{maxZoom:19,attribution:'© OpenStreetMap contributors'}}).addTo(map);
if(points.length && L.heatLayer) {{
  L.heatLayer(points,{{radius:28,blur:22,maxZoom:17}}).addTo(map);
  L.circleMarker(center,{{radius:5,color:'#35ff77',fillOpacity:1}}).addTo(map);
  const bounds=L.latLngBounds(points.map(p=>[p[0],p[1]]).concat([center]));
  map.fitBounds(bounds.pad(0.15),{{maxZoom:15}});
}}
document.getElementById('count').textContent=points.length;
map.on('click', function(event) {{
  window.location.href='imobhunter://mapclick?lat='+event.latlng.lat+'&lon='+event.latlng.lng;
}});
</script></body></html>"""
        self.map_view.setHtml(html)

    @staticmethod
    def _money(value) -> str:
        return "—" if value is None else f"R$ {value:,.2f}"

    def _query_sidra_population(self) -> None:
        query, accepted = QInputDialog.getText(
            self, "IBGE / SIDRA — População",
            "Nome do município ou código IBGE (7 dígitos):"
        )
        if not accepted or not query.strip():
            return
        self.sidra_button.setEnabled(False)
        self.status.setText("Consultando localidades e estimativas oficiais do IBGE em segundo plano…")
        self._sidra_worker = _SidraQueryWorker(query)
        self._sidra_worker.signals.finished.connect(self._sidra_query_finished)
        self._sidra_worker.signals.failed.connect(self._sidra_query_failed)
        QThreadPool.globalInstance().start(self._sidra_worker)

    def _start_sidra_population(self, municipality_code: str) -> None:
        self.status.setText("Consultando a estimativa populacional no SIDRA…")
        self._sidra_worker = _SidraQueryWorker(municipality_code)
        self._sidra_worker.signals.finished.connect(self._sidra_query_finished)
        self._sidra_worker.signals.failed.connect(self._sidra_query_failed)
        QThreadPool.globalInstance().start(self._sidra_worker)

    def _sidra_query_finished(self, payload: dict) -> None:
        if payload.get("kind") == "municipalities":
            items = payload.get("items") or []
            if not items:
                self.sidra_button.setEnabled(True)
                self.status.setText("O IBGE não encontrou municípios com esse nome.")
                QMessageBox.information(self, "IBGE / SIDRA", "Nenhum município encontrado. Confira o nome e tente novamente.")
                return
            if len(items) == 1:
                self._start_sidra_population(items[0]["code"])
                return
            labels = [f'{item["name"]} - {item["state"]} ({item["code"]})' for item in items]
            selected, accepted = QInputDialog.getItem(
                self, "Selecionar município", "O IBGE encontrou mais de um município:",
                labels, 0, False
            )
            if not accepted:
                self.sidra_button.setEnabled(True)
                self.status.setText("Consulta ao IBGE cancelada.")
                return
            index = labels.index(selected)
            self._start_sidra_population(items[index]["code"])
            return

        result = payload.get("result") or {}
        population = result.get("population", "não informado")
        population_text = f"{population:,}".replace(",", ".") if isinstance(population, int) else str(population)
        self.sidra_button.setEnabled(True)
        self.status.setText(
            f'IBGE/SIDRA: {result.get("municipality")} — ano {result.get("period")}; '
            f'população estimada {population_text} pessoas.'
        )
        QMessageBox.information(
            self, "Estimativa populacional — IBGE / SIDRA",
            f"Município: {result.get('municipality')} ({result.get('municipality_code')})\n"
            f"Período de referência: {result.get('period')}\n"
            f"População estimada: {population_text} pessoas\n\n"
            f"Fonte: {result.get('source')}\n"
            f"Tabela: {result.get('source_url')}\n\n"
            "Estimativa oficial do IBGE; o período pode não coincidir com o ano corrente."
        )

    def _sidra_query_failed(self, message: str) -> None:
        self.sidra_button.setEnabled(True)
        self.status.setText("A consulta ao IBGE falhou; o restante do aplicativo continua disponível.")
        QMessageBox.warning(self, "Consulta IBGE / SIDRA", message)

    def _export_results(self) -> None:
        if not self.results:
            QMessageBox.information(self, "Salvar pesquisa", "Faça uma pesquisa antes de exportar.")
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Exportar / salvar pesquisa de Inteligência de Mercado",
            "imobhunter-inteligencia-mercado.csv",
            "CSV — planilha compatível (*.csv);;Excel — pasta de trabalho (*.xlsx);;JSON — dados estruturados (*.json);;HTML — relatório para navegador (*.html)",
        )
        if not path:
            return
        target = Path(path)
        filter_extensions = {
            "CSV — planilha compatível (*.csv)": ".csv",
            "Excel — pasta de trabalho (*.xlsx)": ".xlsx",
            "JSON — dados estruturados (*.json)": ".json",
            "HTML — relatório para navegador (*.html)": ".html",
        }
        expected_suffix = filter_extensions.get(selected_filter)
        if not target.suffix and expected_suffix:
            target = target.with_suffix(expected_suffix)
        elif target.suffix.lower() not in {".csv", ".xlsx", ".json", ".html", ".htm"}:
            QMessageBox.warning(
                self, "Formato não reconhecido",
                "Escolha CSV, Excel (.xlsx), JSON ou HTML para salvar a pesquisa."
            )
            return

        fields = [
            "name", "cnpj", "cnae", "address", "city", "state", "latitude", "longitude",
            "distance_km", "revenue_reported", "revenue_period", "revenue_estimate",
            "estimate_method", "revenue_status", "source", "updated_at",
        ]
        rows = [{field: item.get(field, "") for field in fields} for item in self.results]
        try:
            suffix = target.suffix.lower()
            if suffix == ".csv":
                with target.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(rows)
            elif suffix == ".json":
                payload = {
                    "title": "ImobHunter — Inteligência de Mercado",
                    "query": {
                        "latitude": self.latitude.text().strip(),
                        "longitude": self.longitude.text().strip(),
                        "radius_km": self.radius.text().strip(),
                        "segment": self.segment.currentText(),
                    },
                    "count": len(rows),
                    "records": rows,
                }
                target.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
                    encoding="utf-8",
                )
            elif suffix in {".html", ".htm"}:
                import html

                headers = "".join(f"<th>{html.escape(field)}</th>" for field in fields)
                body = "".join(
                    "<tr>" + "".join(
                        f"<td>{html.escape(str(row.get(field, '') if row.get(field) is not None else ''))}</td>"
                        for field in fields
                    ) + "</tr>"
                    for row in rows
                )
                report = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ImobHunter — Inteligência de Mercado</title>
<style>
body{{font:14px system-ui,sans-serif;background:#07111b;color:#eaf2f7;margin:28px}}
h1{{color:#35ff77}}.meta{{color:#a9bdcb;margin-bottom:18px}}
.table-wrap{{overflow:auto;border:1px solid #254156;border-radius:10px}}
table{{border-collapse:collapse;min-width:100%;background:#0b1926}}
th,td{{padding:9px 11px;text-align:left;border-bottom:1px solid #254156;white-space:nowrap}}
th{{background:#102332;color:#35ff77;position:sticky;top:0}}
tr:nth-child(even){{background:#0d1d2b}}
</style></head><body>
<h1>Inteligência de Mercado</h1>
<div class="meta">Registros: {len(rows)} · Centro: {html.escape(self.latitude.text())}, {html.escape(self.longitude.text())}
· Raio: {html.escape(self.radius.text())} km · Segmento: {html.escape(self.segment.currentText())}</div>
<div class="table-wrap"><table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>
<p class="meta">ImobHunter-BR · Os valores ausentes não foram estimados automaticamente.</p>
</body></html>"""
                target.write_text(report, encoding="utf-8")
            elif suffix == ".xlsx":
                from openpyxl import Workbook
                from openpyxl.styles import Alignment, Font, PatternFill
                from openpyxl.utils import get_column_letter

                workbook = Workbook()
                sheet = workbook.active
                sheet.title = "Inteligência de Mercado"
                sheet.append(fields)
                for row in rows:
                    sheet.append([row.get(field, "") for field in fields])
                for cell in sheet[1]:
                    cell.font = Font(bold=True, color="35FF77")
                    cell.fill = PatternFill("solid", fgColor="102332")
                    cell.alignment = Alignment(vertical="center")
                sheet.freeze_panes = "A2"
                sheet.auto_filter.ref = sheet.dimensions
                for index, field in enumerate(fields, 1):
                    max_length = max(
                        len(field),
                        *(len(str(sheet.cell(row, index).value or "")) for row in range(2, sheet.max_row + 1)),
                    )
                    sheet.column_dimensions[get_column_letter(index)].width = min(max_length + 2, 42)
                workbook.save(target)
        except (OSError, ValueError, TypeError, ImportError) as exc:
            QMessageBox.warning(self, "Salvar pesquisa", f"Não foi possível exportar o arquivo:\n{exc}")
            return
        QMessageBox.information(self, "Pesquisa salva", f"Pesquisa exportada com sucesso:\n{target}")



class ReceitaBrowseDialog(QDialog):
    """Browse the locally imported official CNPJ dataset without network access."""

    def __init__(self, database_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.database_path = database_path
        self.setWindowTitle("ImobHunter • Base oficial de CNPJ local")
        self.resize(1250, 650)
        self.setStyleSheet("""
            QDialog { background:#07111b; color:#eaf2f7; }
            QLabel { color:#eaf2f7; }
            QLineEdit { background:#0b1926; color:#f4f8fb; border:1px solid #254156; border-radius:8px; padding:8px; }
            QPushButton { background:#102332; color:#eaf2f7; border:1px solid #2b4c63; border-radius:9px; padding:8px 12px; }
            QPushButton:hover { border-color:#35ff77; }
            QTableWidget { background:#091722; alternate-background-color:#0d1d2b; gridline-color:#1b3348; color:#eaf2f7; }
            QHeaderView::section { background:#102332; color:#a9bdcb; padding:7px; border:0; }
        """)
        root = QVBoxLayout(self)
        title = QLabel("Base oficial de CNPJ importada no computador")
        title.setStyleSheet("font-size:22px;font-weight:800")
        root.addWidget(title)
        filters = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Razão social, nome fantasia ou CNPJ")
        self.state = QLineEdit()
        self.state.setPlaceholderText("UF (ex.: SP)")
        self.state.setMaximumWidth(100)
        self.cnae = QLineEdit()
        self.cnae.setPlaceholderText("Prefixo CNAE (opcional)")
        self.cnae.setMaximumWidth(180)
        filters.addWidget(self.query, 1)
        filters.addWidget(self.state)
        filters.addWidget(self.cnae)
        search = QPushButton("Pesquisar")
        search.clicked.connect(self._search)
        filters.addWidget(search)
        geocode_selected = QPushButton("Localizar estabelecimento selecionado")
        geocode_selected.setToolTip("Geocodifica somente a linha selecionada e grava as coordenadas pelo CNPJ.")
        geocode_selected.clicked.connect(self._geocode_selected)
        filters.addWidget(geocode_selected)
        export_geo = QPushButton("Exportar endereços para coordenadas")
        export_geo.clicked.connect(self._export_geocoding_csv)
        filters.addWidget(export_geo)
        root.addLayout(filters)
        self.current_rows = []
        self.status = QLabel("Pesquise na base importada; os resultados ficam no PC.")
        root.addWidget(self.status)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Razão social", "Nome fantasia", "CNPJ", "Situação", "CNAE principal", "Endereço", "UF / município", "Porte"])
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)


    def _geocode_selected(self) -> None:
        row_index = self.table.currentRow()
        if row_index < 0 or row_index >= len(self.current_rows):
            QMessageBox.information(self, 'Localizar estabelecimento', 'Pesquise e selecione uma linha antes de localizar.')
            return
        item = self.current_rows[row_index]
        cnpj = str(item.get('cnpj') or '')
        street = ' '.join(str(part).strip() for part in (item.get('street_type'), item.get('street'), item.get('street_number'), item.get('complement'), item.get('neighborhood'), item.get('postal_code')) if part and str(part).strip())
        location = ' '.join(str(part).strip() for part in (item.get('state'), 'Brasil') if part and str(part).strip())
        address = ', '.join(part for part in (street, location) if part)
        if not street or not item.get('state'):
            QMessageBox.warning(self, 'Endereço incompleto', 'O cadastro não tem endereço e UF suficientes.')
            return
        answer = QMessageBox.question(self, 'Confirmar localização individual', f'Localizar somente este estabelecimento?\n\nCNPJ: {cnpj}\n{address}\n\nA precisão depende do endereço cadastral. Consulta individual, com cache local e atribuição OpenStreetMap.')
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            geocoder = CachedAddressGeocoder(self.database_path, 'ImobHunter-BR/0.1 (aplicativo desktop; contato pelo site institucional)')
            result = geocoder.geocode(address)
            saved = save_geocoded_establishment(self.database_path, cnpj, result)
        except (GeocodingError, OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Geocodificação', str(exc))
            return
        self.status.setText(f"Coordenadas vinculadas ao CNPJ {saved['cnpj']} • {result['attribution']}")
        QMessageBox.information(self, 'Estabelecimento localizado', f"{saved['name']}\nCNPJ: {saved['cnpj']}\nLatitude: {result['latitude']}\nLongitude: {result['longitude']}\n\nFonte: {result['provider']} — {result['attribution']}\nCoordenadas salvas localmente. Confira a precisão do ponto antes de usá-lo.")

    def _export_geocoding_csv(self) -> None:
        if not self.current_rows:
            QMessageBox.information(
                self, "Exportar endereços",
                "Faça uma pesquisa com resultados antes de exportar."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar endereços para completar coordenadas",
            "imobhunter-enderecos-coordenadas.csv", "CSV (*.csv)"
        )
        if not path:
            return
        fields = [
            "cnpj", "name", "trade_name", "address", "neighborhood",
            "postal_code", "state", "municipality_code", "cnae",
            "latitude", "longitude", "source", "updated_at"
        ]
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                for item in self.current_rows:
                    writer.writerow({
                        "cnpj": item.get("cnpj", ""),
                        "name": item.get("legal_name") or item.get("trade_name") or "",
                        "trade_name": item.get("trade_name") or "",
                        "address": " ".join(part for part in [
                            item.get("street_type") or "", item.get("street") or "",
                            item.get("street_number") or "", item.get("complement") or ""
                        ] if part),
                        "neighborhood": item.get("neighborhood") or "",
                        "postal_code": item.get("postal_code") or "",
                        "state": item.get("state") or "",
                        "municipality_code": item.get("municipality_code") or "",
                        "cnae": item.get("main_cnae") or "",
                        "latitude": "",
                        "longitude": "",
                        "source": "Receita Federal CNPJ; coordenadas pendentes",
                        "updated_at": "",
                    })
        except OSError as exc:
            QMessageBox.warning(self, "Exportar endereços", str(exc))
            return
        QMessageBox.information(
            self, "Exportar endereços",
            "CSV exportado. Preencha latitude e longitude com coordenadas verificadas e "
            "importe-o pelo botão 'Vincular coordenadas por CNPJ'. O aplicativo não "
            "preenche coordenadas inventadas nem executa geocodificação em massa."
        )

    def _search(self) -> None:
        rows = search_receita_establishments(
            self.database_path, self.query.text(), self.state.text(), self.cnae.text(), 1000
        )
        self.current_rows = rows
        self.table.setRowCount(len(rows))
        for row_index, item in enumerate(rows):
            street = " ".join(part for part in [
                item.get("street_type", ""), item.get("street", ""),
                item.get("street_number", ""), item.get("complement", ""),
                item.get("neighborhood", ""), item.get("postal_code", "")
            ] if part)
            values = [
                item.get("legal_name") or "", item.get("trade_name") or "",
                item.get("cnpj") or "", item.get("registration_status") or "",
                item.get("main_cnae") or "", street,
                " / ".join(part for part in [item.get("state") or "", item.get("municipality_code") or ""] if part),
                item.get("company_size") or ""
            ]
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(str(value)))
        self.status.setText(f"{len(rows)} resultado(s), limite de 1.000 por pesquisa. Dados consultados localmente.")
