"""Non-modal, tabbed presentation of property search results.

The domain data and existing municipal adapters are deliberately left untouched.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .application.export import export_search_result_csv, export_search_result_json
from .application.result_presentation import (
    dossier_caption,
    field_label,
    source_status_label,
    summary_items,
    summary_text,
)
from .application.search import SearchResult
from .domain.models import SearchRequest


class CopyableTable(QTableWidget):
    """Selectable, read-only cells with explicit Ctrl+C and right-click copying."""

    def __init__(self, headers: tuple[str, ...], parent=None) -> None:
        super().__init__(0, len(headers), parent)
        self.setHorizontalHeaderLabels(list(headers))
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.setAlternatingRowColors(True)
        self.setWordWrap(True)
        self.verticalHeader().setDefaultSectionSize(34)
        self.horizontalHeader().setStretchLastSection(True)
        self.setStyleSheet(
            "QTableWidget { background:#0c1926; alternate-background-color:#102331;"
            " color:#edf7f1; gridline-color:#234035; selection-background-color:#245d42;"
            " border:1px solid #254636; border-radius:10px; }"
            "QHeaderView::section { background:#122820; color:#b6d5c4;"
            " border:0; padding:10px; font-weight:700; }"
        )

    def copy_selected(self) -> None:
        indexes = self.selectedIndexes()
        if not indexes:
            current = self.currentIndex()
            if current.isValid():
                indexes = [current]
        if not indexes:
            return
        cells = {}
        for index in indexes:
            item = self.item(index.row(), index.column())
            cells[(index.row(), index.column())] = item.text() if item else ""
        row_ids = sorted({row for row, _ in cells})
        col_ids = sorted({column for _, column in cells})
        text = "\n".join(
            "\t".join(cells.get((row, column), "") for column in col_ids)
            for row in row_ids
        )
        QApplication.clipboard().setText(text)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selected()
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        action = menu.addAction("Copiar seleção")
        action.setEnabled(bool(self.selectedIndexes()) or self.currentIndex().isValid())
        action.triggered.connect(self.copy_selected)
        menu.exec(event.globalPos())


class SearchResultsWindow(QMainWindow):
    """Each search has its own independent window and its own timeout timer."""

    def __init__(self, request: SearchRequest, map_factory=None) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self._map_factory = map_factory
        self._result: SearchResult | None = None
        self._map_records = []
        self._open_maps = []
        self._completed = False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        query = " ".join(p for p in (request.address, request.number) if p)
        if not query and request.block and request.lot:
            query = f"Quadra {request.block}, lote {request.lot}"
        if not query:
            query = request.cib or "Pesquisa cadastral"
        location = ", ".join(p for p in (request.city, request.state) if p)
        self.setWindowTitle(f"ImobHunter-BR • {query} • {location}".strip(" •"))
        self.resize(1240, 800)
        self.setMinimumSize(850, 550)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        heading = QLabel("Pesquisa imobiliária — dossiê")
        heading.setObjectName("resultTitle")
        layout.addWidget(heading)
        subtitle = QLabel(
            f"{query}  ·  {location}\n"
            "Esta janela é independente: é possível trabalhar no restante do ImobHunter."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)

        self.summary = QLabel("Consultando fontes cadastradas…")
        self.summary.setWordWrap(True)
        self.summary.setObjectName("section")
        layout.addWidget(self.summary)

        actions = QHBoxLayout()
        self.copy_summary_button = QPushButton("Copiar resumo")
        self.copy_summary_button.setEnabled(False)
        self.copy_summary_button.clicked.connect(self._copy_summary)
        actions.addWidget(self.copy_summary_button)
        self.export_csv_button = QPushButton("Exportar CSV")
        self.export_csv_button.setEnabled(False)
        self.export_csv_button.clicked.connect(self._export_csv)
        actions.addWidget(self.export_csv_button)
        self.export_json_button = QPushButton("Exportar JSON")
        self.export_json_button.setEnabled(False)
        self.export_json_button.clicked.connect(self._export_json)
        actions.addWidget(self.export_json_button)
        self.map_button = QPushButton("Ver localização / lotes")
        self.map_button.setEnabled(False)
        self.map_button.clicked.connect(self._open_cadastral_map)
        actions.addWidget(self.map_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet(
            "QTabBar::tab { padding:11px 18px; background:#10241e;"
            " color:#b7cfbf; border:1px solid #264333; }"
            "QTabBar::tab:selected { color:#35ff77; background:#153b29; }"
        )
        layout.addWidget(self.tabs, 1)

        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.overview_scroll = QScrollArea()
        self.overview_scroll.setWidgetResizable(True)
        self.overview_host = QWidget()
        self.overview_cards = QVBoxLayout(self.overview_host)
        self.overview_cards.setSpacing(12)
        self.overview_scroll.setWidget(self.overview_host)
        splitter.addWidget(self.overview_scroll)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Condição das fontes consultadas"))
        self.source_brief = QTextBrowser()
        self.source_brief.setText(
            "Aguardando respostas. Cada fonte será identificada como disponível, "
            "sem resultados, indisponível ou com erro."
        )
        right_layout.addWidget(self.source_brief, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        overview_layout.addWidget(splitter)
        self.tabs.addTab(overview, "Resumo cadastral")

        facts_page = QWidget()
        facts_layout = QVBoxLayout(facts_page)
        tools = QHBoxLayout()
        self.filter_field = QLineEdit()
        self.filter_field.setPlaceholderText("Filtrar por imóvel, campo, valor ou fonte…")
        self.filter_field.textChanged.connect(self._filter_facts)
        tools.addWidget(self.filter_field, 1)
        copy_facts = QPushButton("Copiar seleção")
        copy_facts.clicked.connect(lambda: self.facts_table.copy_selected())
        tools.addWidget(copy_facts)
        facts_layout.addLayout(tools)
        self.facts_table = CopyableTable(
            ("Imóvel", "Informação", "Valor", "Fonte", "Confiança")
        )
        facts_layout.addWidget(self.facts_table, 1)
        facts_help = QLabel(
            "Selecione um ou vários campos e pressione Ctrl+C; botão direito também copia. "
            "Todos os atributos retornados permanecem disponíveis para conferência."
        )
        facts_help.setObjectName("muted")
        facts_help.setWordWrap(True)
        facts_layout.addWidget(facts_help)
        self.tabs.addTab(facts_page, "Dados completos")

        sources_page = QWidget()
        sources_layout = QVBoxLayout(sources_page)
        copy_sources = QPushButton("Copiar seleção das fontes")
        copy_sources.clicked.connect(lambda: self.sources_table.copy_selected())
        sources_layout.addWidget(copy_sources, alignment=Qt.AlignmentFlag.AlignRight)
        self.sources_table = CopyableTable(("Fonte", "Situação", "Registros", "Detalhes"))
        sources_layout.addWidget(self.sources_table, 1)
        self.tabs.addTab(sources_page, "Fontes e diagnósticos")
        self.setCentralWidget(root)

        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._show_timeout)
        self._watchdog.start(90_000)

    @staticmethod
    def _set_cell(table: QTableWidget, row: int, column: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setToolTip(text)
        table.setItem(row, column, item)

    def _clear_overview(self) -> None:
        while self.overview_cards.count():
            entry = self.overview_cards.takeAt(0)
            if entry.widget() is not None:
                entry.widget().deleteLater()

    def _render_overview(self, result: SearchResult) -> None:
        self._clear_overview()
        if not result.dossiers:
            note = QLabel(
                "Nenhum imóvel cadastral foi consolidado. Isso não significa que o "
                "endereço não exista: confira abaixo as respostas das fontes."
            )
            note.setWordWrap(True)
            self.overview_cards.addWidget(note)
        for index, dossier in enumerate(result.dossiers, 1):
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            title = QLabel(f"Imóvel {index} — {dossier_caption(dossier)}")
            title.setObjectName("resultTitle")
            title.setWordWrap(True)
            card_layout.addWidget(title)
            for label, value in summary_items(dossier):
                row = QHBoxLayout()
                name = QLabel(label)
                name.setMinimumWidth(155)
                name.setMaximumWidth(205)
                name.setWordWrap(True)
                row.addWidget(name)
                field = QLineEdit(value)
                field.setReadOnly(True)
                field.setToolTip(value)
                row.addWidget(field, 1)
                copy = QPushButton("Copiar")
                copy.setToolTip(f"Copiar {label}")
                copy.clicked.connect(
                    lambda checked=False, v=value: QApplication.clipboard().setText(v)
                )
                row.addWidget(copy)
                card_layout.addLayout(row)
            if not summary_items(dossier):
                missing = QLabel("Nenhum campo cadastral essencial informado pelas fontes.")
                missing.setWordWrap(True)
                card_layout.addWidget(missing)
            self.overview_cards.addWidget(card)
        self.overview_cards.addStretch(1)

    def _render_facts(self, result: SearchResult) -> None:
        self.facts_table.setSortingEnabled(False)
        rows = [
            (str(index), field_label(fact.field), str(fact.value),
             fact.provenance.source_id, f"{fact.provenance.confidence:.0%}")
            for index, dossier in enumerate(result.dossiers, 1)
            for fact in dossier.facts
        ]
        self.facts_table.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for column, value in enumerate(values):
                self._set_cell(self.facts_table, row_index, column, value)
        self.facts_table.resizeColumnsToContents()
        self.facts_table.horizontalHeader().setStretchLastSection(True)
        self.facts_table.setSortingEnabled(True)
        self._filter_facts(self.filter_field.text())

    def _filter_facts(self, query: str) -> None:
        needle = query.casefold().strip()
        for row in range(self.facts_table.rowCount()):
            values = (
                self.facts_table.item(row, col).text()
                for col in range(self.facts_table.columnCount())
                if self.facts_table.item(row, col) is not None
            )
            self.facts_table.setRowHidden(
                row, bool(needle) and not any(needle in value.casefold() for value in values)
            )

    def _render_sources(self, result: SearchResult) -> None:
        self.sources_table.setRowCount(len(result.sources))
        summary_parts = []
        for row, source in enumerate(result.sources):
            values = (
                source.name,
                source_status_label(source.status),
                str(source.records_count),
                source.message or "Fonte consultada sem mensagem adicional.",
            )
            for column, value in enumerate(values):
                self._set_cell(self.sources_table, row, column, value)
            summary_parts.append(
                f"<p><b>{escape(source.name)}</b><br>"
                f"{escape(source_status_label(source.status))} · "
                f"{source.records_count} registro(s)<br>"
                f"{escape(source.message or '')}</p>"
            )
        self.sources_table.resizeColumnsToContents()
        self.sources_table.horizontalHeader().setStretchLastSection(True)
        self.source_brief.setHtml(
            "".join(summary_parts) or "Nenhuma fonte foi registrada nesta pesquisa."
        )

    def _copy_summary(self) -> None:
        if self._result is not None:
            QApplication.clipboard().setText(summary_text(self._result))

    def _show_timeout(self) -> None:
        if self._completed:
            return
        self._completed = True
        self.summary.setText(
            "A consulta ultrapassou 90 segundos. O aplicativo permanece disponível. "
            "Os resultados ainda poderão aparecer caso a fonte finalize."
        )
        self.source_brief.setPlainText(
            "Uma ou mais consultas demoraram além do esperado. "
            "Não conclua que o imóvel inexiste por causa de um timeout."
        )

    def set_result(self, result: SearchResult) -> None:
        self._result = result
        self._completed = True
        self._watchdog.stop()
        self.copy_summary_button.setEnabled(True)
        self.export_csv_button.setEnabled(True)
        self.export_json_button.setEnabled(True)
        self._map_records = [
            record for record in result.records
            if record.attributes.get("geometry_geojson")
            or (record.latitude is not None and record.longitude is not None)
        ]
        self.map_button.setEnabled(bool(self._map_records) and self._map_factory is not None)
        answered = sum(source.status in {"ok", "no_results"} for source in result.sources)
        self.summary.setText(
            f"{len(result.records)} registro(s) retornado(s) · "
            f"{len(result.dossiers)} imóvel(is) individualizado(s) · "
            f"{answered} de {len(result.sources)} fonte(s) responderam"
        )
        self._render_overview(result)
        self._render_facts(result)
        self._render_sources(result)

    def set_error(self, message: str) -> None:
        self._completed = True
        self._watchdog.stop()
        self.summary.setText("A consulta não pôde ser concluída.")
        self.source_brief.setPlainText(message)

    def _open_cadastral_map(self) -> None:
        if not self._map_records or self._map_factory is None:
            return
        # This is still the existing map widget; a fully integrated GIS is Stage 2.
        # It must not block the dossier or the main application in the meantime.
        window = self._map_factory(self._map_records, self)
        window.setWindowModality(Qt.WindowModality.NonModal)
        window.setWindowFlag(Qt.WindowType.Window, True)
        self._open_maps.append(window)
        window.show()
        window.raise_()

    def _export_csv(self) -> None:
        if self._result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar dossiê CSV", "imobhunter-dossie.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            export_search_result_csv(self._result, Path(path))
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Falha ao exportar CSV", str(exc))

    def _export_json(self) -> None:
        if self._result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar dossiê JSON", "imobhunter-dossie.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            export_search_result_json(self._result, Path(path))
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Falha ao exportar JSON", str(exc))
