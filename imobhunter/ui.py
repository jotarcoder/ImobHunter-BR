from __future__ import annotations

from html import escape
from pathlib import Path
import sys
import uuid

from PySide6.QtCore import QThreadPool, QObject, QRunnable, QUrl, Qt, Signal, Slot, QTimer, QSize
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
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .application.coverage import DDDCoverageRegistry, load_ddd_coverage
from .application.search import SearchResult, SearchService
from .domain.models import SearchRequest
from .ui_market import MarketIntelligenceDialog
from .ui_settings import SourceSettingsDialog
from .ui_results import SearchResultsWindow
from .ui_responsive import fit_window_to_screen


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
                    errors = getattr(self.source, "last_errors", {})
                    city = (self.request.city or "").casefold()
                    failure = next(
                        (
                            str(detail) for place, detail in errors.items()
                            if place.casefold() == city
                        ),
                        None,
                    ) if isinstance(errors, dict) else None
                    if failure and self.source.source_id == "official_municipal_services":
                        state = "error"
                        message = f"Serviço municipal indisponível: {failure}"
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



class MainWindow(QMainWindow):
    def __init__(self, service: SearchService, coverage: DDDCoverageRegistry) -> None:
        super().__init__()
        self.service = service
        self.coverage = coverage
        # Avoid holding the PySide wrapper of Qt's shared global pool.
        # QApplication owns this pool, so closing an independent window does
        # not destroy active search workers or tear down the Qt singleton.
        self.thread_pool = QThreadPool(QApplication.instance())
        self.thread_pool.setMaxThreadCount(8)
        self._result_windows: list[SearchResultsWindow] = []
        self._search_workers: dict[SearchResultsWindow, SearchWorker] = {}
        self._utility_dialogs: list[QDialog] = []
        self.setWindowTitle("ImobHunter-BR")
        logo_path = Path(__file__).resolve().parent / "assets" / "logo.svg"
        self.setWindowIcon(QIcon(str(logo_path)))
        cursor_path = Path(__file__).resolve().parent / "assets" / "magnetic_cursor.svg"
        cursor_pixmap = QPixmap(str(cursor_path)).scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._magnetic_cursor = QCursor(cursor_pixmap, 4, 3)
        self.setCursor(self._magnetic_cursor)
        self.resize(1320, 820)
        self.setMinimumSize(650, 440)
        self._build()
        for button in self.findChildren(QPushButton):
            button.setCursor(self._magnetic_cursor)
        for field in self.findChildren(QLineEdit):
            field.setCursor(Qt.CursorShape.IBeamCursor)
        self._populate_coverage()
        fit_window_to_screen(self, QSize(1320, 820), QSize(650, 440))

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

        root.setLayout(shell)
        # The primary search area also remains accessible at high Windows DPI:
        # the fixed-width sidebar stays usable while content may scroll.
        self.content_scroll = QScrollArea()
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.content_scroll.setWidget(content)
        shell.addWidget(self.content_scroll, 1)
        self.setCentralWidget(root)

    def _show_market_intelligence(self) -> None:
        dialog = getattr(self, "_market_window", None)
        if dialog is None:
            dialog = MarketIntelligenceDialog(self)
            dialog.setWindowFlag(Qt.WindowType.Window, True)
            dialog.setWindowModality(Qt.WindowModality.NonModal)
            self._market_window = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

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
        dialog.setMinimumSize(500, 380)
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
        # A fixed row for every adapter forced this dialog below the taskbar.
        # Put the tests into their own vertical scroll area.
        tests_scroll = QScrollArea()
        tests_scroll.setWidgetResizable(True)
        tests_scroll.setMinimumHeight(85)
        tests_host = QWidget()
        tests_layout = QVBoxLayout(tests_host)
        tests_layout.setContentsMargins(6, 6, 6, 6)
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
            tests_layout.addLayout(row)
            status_labels[source.source_id] = label
            buttons[source.source_id] = button
        tests_layout.addStretch(1)
        tests_scroll.setWidget(tests_host)
        root.addWidget(tests_scroll, 1)

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
        dialog.setWindowFlag(Qt.WindowType.Window, True)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        fit_window_to_screen(dialog, QSize(980, 760), QSize(500, 380))
        self._utility_dialogs.append(dialog)
        dialog.show()

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
        dialog.setWindowFlag(Qt.WindowType.Window, True)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        self._utility_dialogs.append(dialog)
        dialog.show()

    def _show_settings(self) -> None:
        dialog = SourceSettingsDialog(self.service.registry, self)
        dialog.setWindowFlag(Qt.WindowType.Window, True)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.finished.connect(
            lambda result: self.search_status.setText(
                "Configurações aplicadas. As próximas pesquisas usarão as fontes atualizadas."
            ) if result == QDialog.DialogCode.Accepted else None
        )
        self._utility_dialogs.append(dialog)
        dialog.show()

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
        # Allow navigation and a second search, but bound concurrent fan-out.
        if len(self._search_workers) >= 2:
            self.search_status.setText(
                "Duas pesquisas estão em andamento. Acompanhe os dossiês abertos."
            )
            return
        result_window = SearchResultsWindow(request)
        self._result_windows.append(result_window)
        result_window.show()
        result_window.raise_()
        result_window.activateWindow()
        worker = SearchWorker(self.service, request)
        self._search_workers[result_window] = worker
        self.search_button.setEnabled(len(self._search_workers) < 2)
        self.search_status.setText(
            "Consultando fontes… O restante do aplicativo continua disponível."
        )
        worker.signals.finished.connect(
            lambda result, w=result_window: self._search_finished_in_window(w, result)
        )
        worker.signals.failed.connect(
            lambda message, w=result_window: self._search_failed_in_window(w, message)
        )
        self.thread_pool.start(worker)

    def _update_search_controls(self) -> None:
        self.search_button.setEnabled(len(self._search_workers) < 2)
        if self._search_workers:
            self.search_status.setText(
                f"{len(self._search_workers)} pesquisa(s) ainda em andamento."
            )
        else:
            self.search_status.setText("Pronto para outra pesquisa.")

    def _search_finished_in_window(
        self, window: SearchResultsWindow, result: SearchResult
    ) -> None:
        self._search_workers.pop(window, None)
        window.set_result(result)
        sources = result.sources
        active = sum(source.status in {"ok", "no_results"} for source in sources)
        self.metric_properties.set_value(str(len(result.dossiers)))
        self.metric_sources.set_value(f"{active}/{len(sources)}")
        if result.dossiers:
            score = sum(dossier.score for dossier in result.dossiers) / len(result.dossiers)
            self.metric_confidence.set_value(f"{score:.0f}/100")
        else:
            self.metric_confidence.set_value("—")
        self._update_search_controls()

    def _search_failed_in_window(
        self, window: SearchResultsWindow, message: str
    ) -> None:
        self._search_workers.pop(window, None)
        window.set_error(message)
        self._update_search_controls()


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
