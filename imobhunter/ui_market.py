from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from .application.market_intelligence import MarketIntelligenceStore


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
        import_button = QPushButton("Importar CSV local")
        import_button.clicked.connect(self._import_csv)
        actions.addWidget(import_button)
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
