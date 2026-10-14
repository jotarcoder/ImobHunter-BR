from __future__ import annotations

from html import escape
from pathlib import Path
import sys

from PySide6.QtCore import QThreadPool, QObject, QRunnable, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QCursor, QDesktopServices, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .application.coverage import DDDCoverageRegistry, load_ddd_coverage
from .application.search import SearchResult, SearchService
from .domain.models import SearchRequest
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


class MainWindow(QMainWindow):
    def __init__(self, service: SearchService, coverage: DDDCoverageRegistry) -> None:
        super().__init__()
        self.service = service
        self.coverage = coverage
        self.thread_pool = QThreadPool.globalInstance()
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
        row.addWidget(self.city)
        row.addWidget(self.state)
        row.addWidget(self.search_button)
        hero_layout.addLayout(row)

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
        layout.addWidget(results, 1)

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
        self.search_button.setEnabled(False)
        self.search_status.setText("Consultando fontes configuradas…")
        worker = SearchWorker(self.service, request)
        worker.signals.finished.connect(self._search_finished)
        worker.signals.failed.connect(self._search_failed)
        self.thread_pool.start(worker)

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
            "attribute:sql": "Contribuinte IPTU / SQL", "attribute:iptu_contributor": "Contribuinte IPTU / SQL",
            "attribute:built_area_m2": "Área construída (m²)", "attribute:door_number": "Número predial",
            "attribute:sector": "Setor fiscal", "attribute:condominium": "Condomínio",
            "attribute:lot_status": "Situação do lote", "attribute:lot_type": "Tipo de lote",
        }
        shown_iptu = False
        for fact in dossier.facts:
            if fact.field == "registry_number":
                continue
            if fact.field in {"attribute:sql", "attribute:iptu_contributor"}:
                if shown_iptu:
                    continue
                shown_iptu = True
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            raw_label = labels.get(fact.field, fact.field.replace("attribute:", "").replace("_", " ").capitalize())
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
        if not shown_iptu:
            note = QLabel("Contribuinte IPTU / SQL não veio no registro consolidado. A fonte municipal precisa retornar esse campo; não é seguro deduzi-lo de outro identificador.")
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
