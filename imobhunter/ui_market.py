from __future__ import annotations

import csv
import json
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from .application.market_intelligence import MarketIntelligenceStore
from .application.receita_import import import_receita_archives, search_receita_establishments
from .application.receita_geo import import_receita_coordinates, save_geocoded_establishment
from .application.address_geocoding import CachedAddressGeocoder, GeocodingError


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


class MarketIntelligenceDialog(QDialog):
    """Local-only company and geographic market explorer."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ImobHunter • Inteligência de Mercado")
        self.resize(980, 620)
        self.setMinimumSize(860, 540)
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
        title = QLabel("Inteligência de Mercado")
        title.setStyleSheet("font-size:26px;font-weight:800;color:#f4f8fb")
        root.addWidget(title)
        subtitle = QLabel("Explore empresas por raio e consulte dados econômicos armazenados no seu computador.")
        subtitle.setObjectName("muted")
        root.addWidget(subtitle)

        controls = QHBoxLayout()
        self.latitude = QLineEdit()
        self.latitude.setPlaceholderText("Latitude do ponto central")
        self.longitude = QLineEdit()
        self.longitude.setPlaceholderText("Longitude do ponto central")
        self.radius = QLineEdit("2")
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
        root.addLayout(controls)

        actions = QHBoxLayout()
        geocode_button = QPushButton("Localizar endereço")
        geocode_button.setToolTip("Localiza um endereço por vez e preenche as coordenadas para a pesquisa por raio.")
        geocode_button.clicked.connect(self._geocode_address)
        actions.addWidget(geocode_button)
        import_button = QPushButton("Importar CSV local")
        import_button.clicked.connect(self._import_csv)
        actions.addWidget(import_button)
        receita_button = QPushButton("Importar ZIP oficial do CNPJ")
        receita_button.clicked.connect(self._import_receita)
        actions.addWidget(receita_button)
        geo_button = QPushButton("Vincular coordenadas por CNPJ")
        geo_button.clicked.connect(self._import_coordinates)
        actions.addWidget(geo_button)
        browse_button = QPushButton("Consultar base oficial")
        browse_button.clicked.connect(self._browse_receita)
        actions.addWidget(browse_button)
        self.online_button = QPushButton("Buscar empresas online")
        self.online_button.setToolTip("Consulta estabelecimentos mapeados no OpenStreetMap dentro do raio informado.")
        self.online_button.clicked.connect(self._search_online)
        actions.addWidget(self.online_button)
        export_button = QPushButton("Exportar resultados CSV")
        export_button.clicked.connect(self._export_csv)
        actions.addWidget(export_button)
        actions.addStretch()
        self.status = QLabel("Banco local vazio. Importe um CSV autorizado para pesquisar.")
        self.status.setObjectName("muted")
        actions.addWidget(self.status)
        root.addLayout(actions)

        map_title = QLabel("Mapa de calor — concentração de estabelecimentos")
        map_title.setStyleSheet("font-size:16px;font-weight:750;")
        root.addWidget(map_title)
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            self.map_view = QWebEngineView(self)
            self.map_view.setMinimumHeight(250)
            root.addWidget(self.map_view, 2)
        except ImportError:
            self.map_view = None
            fallback = QLabel(
                "A visualização cartográfica requer o componente Qt WebEngine desta instalação. "
                "Os resultados e coordenadas continuam disponíveis na tabela."
            )
            fallback.setObjectName("muted")
            fallback.setWordWrap(True)
            root.addWidget(fallback)

        self.table = QTableWidget(0, 8)
        self.table.setMinimumHeight(160)
        self.table.setHorizontalHeaderLabels([
            "Empresa", "CNPJ", "CNAE", "Endereço", "Distância km",
            "Faturamento divulgado", "Faturamento estimado", "Fonte / atualização"
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)
        note = QLabel("Os valores de faturamento só são exibidos quando constam no arquivo importado. Estimativas devem incluir metodologia e fonte; o aplicativo não inventa valores nem consulta o seu servidor.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        root.addWidget(note)
        self.results = []

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
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.results))
        for row_index, item in enumerate(self.results):
            reported = item.get("revenue_reported")
            estimate = item.get("revenue_estimate")
            values = [
                item.get("name",""), item.get("cnpj",""), item.get("cnae",""),
                item.get("address",""), f'{item["distance_km"]:.2f}',
                self._money(reported), self._money(estimate),
                " • ".join(x for x in [item.get("source",""), item.get("updated_at","")] if x),
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if column in (4,5,6):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row_index, column, cell)
        self.table.setSortingEnabled(True)
        self._render_heatmap(lat, lon)
        self.status.setText(f"{len(self.results)} empresa(s) encontrada(s) no raio de {radius:g} km.")

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
</script></body></html>"""
        self.map_view.setHtml(html)

    @staticmethod
    def _money(value) -> str:
        return "—" if value is None else f"R$ {value:,.2f}"

    def _export_csv(self) -> None:
        if not self.results:
            QMessageBox.information(self, "Exportar", "Faça uma pesquisa antes de exportar.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exportar resultados", "imobhunter-empresas.csv", "CSV (*.csv)")
        if not path:
            return
        fields = ["name","cnpj","cnae","address","city","state","latitude","longitude","distance_km",
                  "revenue_reported","revenue_period","revenue_estimate","estimate_method","revenue_status","source","updated_at"]
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(self.results)
        except OSError as exc:
            QMessageBox.warning(self, "Exportar", str(exc))
            return
        QMessageBox.information(self, "Exportar", "Resultados exportados localmente.")



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
