from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import QThreadPool, QObject, QRunnable, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
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


APP_STYLE = """
QMainWindow, QWidget { background: #0b0f17; color: #e7edf7; font-family: "Segoe UI"; }
QFrame#sidebar { background: #0f1520; border-right: 1px solid #202938; }
QFrame#card { background: #111925; border: 1px solid #202b3b; border-radius: 16px; }
QFrame#hero { background: #111a29; border: 1px solid #26344a; border-radius: 20px; }
QLabel#brand { font-size: 22px; font-weight: 800; color: #f6f8fc; }
QLabel#muted { color: #8e9bb0; font-size: 12px; }
QLabel#title { font-size: 30px; font-weight: 800; color: #f6f8fc; }
QLabel#section { font-size: 14px; font-weight: 700; color: #dbe4f3; }
QLabel#metric { font-size: 25px; font-weight: 800; color: #f6f8fc; }
QLineEdit {
    background: #0b111c; border: 1px solid #29364a; border-radius: 11px;
    padding: 11px 13px; color: #f6f8fc; selection-background-color: #315b9b;
}
QLineEdit:focus { border: 1px solid #5b8def; }
QPushButton {
    background: #182235; border: 1px solid #2a3950; border-radius: 10px;
    padding: 9px 13px; color: #e9eff9; font-weight: 650;
}
QPushButton:hover { background: #21304a; border-color: #3e587e; }
QPushButton:pressed { background: #162035; }
QPushButton#primary {
    background: #4f7cff; border: 1px solid #5e88ff; color: white;
    padding: 11px 18px; border-radius: 11px;
}
QPushButton#primary:hover { background: #628cff; }
QPushButton#nav {
    text-align: left; padding: 10px 12px; border: 0; background: transparent;
    color: #9ca9bc; border-radius: 9px;
}
QPushButton#nav:hover { background: #182233; color: #eef4ff; }
QPushButton#ddd {
    padding: 7px 12px; border-radius: 9px; background: #131d2c;
    border: 1px solid #26354b; min-width: 64px;
}
QPushButton#ddd:hover { background: #1b2a41; border-color: #4f7cff; }
QScrollArea { border: 0; background: transparent; }
QProgressBar { background: #182233; border: 0; border-radius: 4px; height: 7px; }
QProgressBar::chunk { background: #4f7cff; border-radius: 4px; }
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
        except (RuntimeError, ValueError) as exc:
            self.signals.failed.emit(str(exc))


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
        self.resize(1280, 820)
        self.setMinimumSize(1050, 700)
        self._build()
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
        side.addSpacing(24)
        for text in ("⌕  Prospecção", "▦  Cobertura", "◈  Fontes", "⚙  Configurações"):
            button = QPushButton(text)
            button.setObjectName("nav")
            side.addWidget(button)
        downloads = QPushButton("↓  Downloads e políticas")
        downloads.setObjectName("nav")
        downloads.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/jotarcoder/ImobHunter-BR/releases")))
        side.addWidget(downloads)
        side.addStretch()
        local = QLabel("●  Processamento local")
        local.setStyleSheet("color:#72d49a;font-size:12px;font-weight:650;")
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
        self.coverage_scroll.setFixedHeight(56)
        coverage_host = QWidget()
        self.coverage_layout = QHBoxLayout(coverage_host)
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
        results_title.setObjectName("section")
        results_layout.addWidget(results_title)
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
        if not address or not city or len(state) != 2:
            QMessageBox.warning(
                self,
                "Dados incompletos",
                "Informe endereço, cidade e UF. O número é opcional.",
            )
            return

        request = SearchRequest(
            address=address,
            number=number,
            city=city,
            state=state,
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
