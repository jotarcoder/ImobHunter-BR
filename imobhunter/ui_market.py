from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from .application.market_intelligence import MarketIntelligenceStore
from .application.receita_import import import_receita_archives, search_receita_establishments
from .application.receita_geo import import_receita_coordinates
from .application.address_geocoding import CachedAddressGeocoder, GeocodingError


class MarketIntelligenceDialog(QDialog):
    """Local-only company and geographic market explorer."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ImobHunter • Inteligência de Mercado")
        self.resize(1180, 720)
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
        export_button = QPushButton("Exportar resultados CSV")
        export_button.clicked.connect(self._export_csv)
        actions.addWidget(export_button)
        actions.addStretch()
        self.status = QLabel("Banco local vazio. Importe um CSV autorizado para pesquisar.")
        self.status.setObjectName("muted")
        actions.addWidget(self.status)
        root.addLayout(actions)

        self.table = QTableWidget(0, 8)
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
        self.status.setText(f"{len(self.results)} empresa(s) encontrada(s) no raio de {radius:g} km.")

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
