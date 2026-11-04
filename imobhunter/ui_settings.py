from __future__ import annotations

import sqlite3
from pathlib import Path

from urllib.parse import urlparse

from PySide6.QtCore import QSettings, QObject, QRunnable, QThreadPool, Signal, QSize, Qt
from .application.municipal_endpoints import settings_endpoint_rows
from .application.custom_municipal_sources import CustomMunicipalStore, infer_protocol
from .sources.custom_municipal import reload_custom_sources
from .sources.sp_bertioga_local import BertiogaLocalStore
from .sources.pe_recife_iptu_local import RecifeIPTULocalStore
from .application.source_probe import EndpointProbe, is_official_service_url, probe_endpoint
from .sources.geosampa import DEFAULT_WFS_URL
from .ui_responsive import fit_window_to_screen

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)


# Always generated from the URLs used by the actual municipal adapters.
# GeoSampa is already displayed as its own editable row above this list.
MUNICIPAL_SOURCE_ENDPOINTS = tuple(
    source for source in settings_endpoint_rows() if source["id"] != "sao_paulo"
)

SOURCE_FILES = (
    ("ibge_cnefe", "IBGE / CNEFE", "data_path", "CSV, ZIP, JSON ou GeoJSON"),
    ("sinter_cib", "SINTER / CIB", "data_path", "CSV, JSON ou GeoJSON"),
    ("sncr", "SNCR / INCRA", "data_path", "CSV, JSON ou GeoJSON"),
    ("sicar", "SICAR / CAR", "data_path", "CSV, JSON ou GeoJSON"),
    ("sigef", "SIGEF / INCRA", "data_path", "CSV, JSON ou GeoJSON"),
    ("cnir", "CNIR / CAFIR", "data_path", "CSV, JSON ou GeoJSON"),
    ("cnpj", "Receita Federal / CNPJ", "data_path", "CSV ou JSON"),
    ("municipal_iptu", "IPTU municipal", "data_path", "CSV ou JSON"),
    ("osm", "OpenStreetMap (base local)", "data_path", "CSV, JSON, GeoJSON ou JSONL"),
)


class MunicipalProbeSignals(QObject):
    finished = Signal(str, object)


class MunicipalProbeWorker(QRunnable):
    """Probe capabilities in a Qt worker; do not block the settings dialog."""

    def __init__(self, source: dict[str, str]) -> None:
        super().__init__()
        self.source = source
        self.signals = MunicipalProbeSignals()

    def run(self) -> None:
        result = probe_endpoint(self.source)
        self.signals.finished.emit(self.source["id"], result)


class BertiogaImportSignals(QObject):
    finished = Signal(object)


class BertiogaImportWorker(QRunnable):
    """Index the municipal GeoJSON trio off the Qt UI thread."""

    def __init__(self, paths: tuple[Path, Path, Path]) -> None:
        super().__init__()
        self.paths = paths
        self.signals = BertiogaImportSignals()

    def run(self) -> None:
        try:
            counts = BertiogaLocalStore().import_files(*self.paths)
            self.signals.finished.emit({"ok": True, "counts": counts})
        except Exception as exc:  # noqa: BLE001 - keep Qt thread alive on invalid municipal files
            self.signals.finished.emit({
                "ok": False,
                "message": f"{type(exc).__name__}: {str(exc)[:220]}",
            })


class RecifeIPTUImportSignals(QObject):
    finished = Signal(object)


class RecifeIPTUImportWorker(QRunnable):
    """Stream large public CSVs into local SQLite, without blocking Qt."""

    def __init__(self, paths: tuple[Path, ...]) -> None:
        super().__init__()
        self.paths = paths
        self.signals = RecifeIPTUImportSignals()

    def run(self) -> None:
        try:
            counts = RecifeIPTULocalStore().import_files(self.paths)
            self.signals.finished.emit({"ok": True, "counts": counts})
        except Exception as exc:  # noqa: BLE001 - report corrupt municipal files without Qt crash
            self.signals.finished.emit({
                "ok": False, "message": f"{type(exc).__name__}: {str(exc)[:220]}",
            })


class SourceSettingsDialog(QDialog):
    """Configures local datasets and supported source endpoints for this user."""

    def __init__(self, registry, parent=None, custom_store=None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.custom_store = custom_store or CustomMunicipalStore()
        self.bertioga_store = BertiogaLocalStore()
        self._bertioga_import_worker: BertiogaImportWorker | None = None
        self.recife_store = RecifeIPTULocalStore()
        self._recife_import_worker: RecifeIPTUImportWorker | None = None
        self.settings = QSettings("ImobHunter", "ImobHunter-BR")
        self.path_fields: dict[str, QLineEdit] = {}
        self._municipal_probe_workers: dict[str, MunicipalProbeWorker] = {}
        self._municipal_probe_buttons: dict[str, QPushButton] = {}
        self._municipal_probe_labels: dict[str, QLabel] = {}
        self.setWindowTitle("Configurações de fontes e acessos")
        self.resize(820, 720)
        self.setMinimumSize(480, 360)
        self.setStyleSheet("""
            QDialog { background:#08120b; color:#eaf2ed; }
            QLabel { color:#eaf2ed; }
            QLabel#muted { color:#91af97; }
            QLineEdit { background:#101c13; color:#f4fbf5; border:1px solid #2a5334; border-radius:7px; padding:8px; }
            QPushButton { background:#14291a; color:#eaf2ed; border:1px solid #2a5334; border-radius:8px; padding:8px 12px; }
            QPushButton#primary { background:#35ff77; color:#04110a; font-weight:800; }
        """)
        root = QVBoxLayout(self)
        title = QLabel("Fontes de dados e credenciais")
        title.setStyleSheet("font-size:22px;font-weight:800;")
        root.addWidget(title)
        intro = QLabel(
            "Selecione exportações autorizadas locais e configure endpoints para os quais "
            "você possui acesso. Os caminhos são aplicados imediatamente à pesquisa nesta sessão "
            "e salvos nas configurações do usuário. A disponibilidade depende do serviço e das "
            "permissões concedidas pelo órgão."
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        root.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setMinimumSize(0, 0)
        host = QWidget()
        form = QFormLayout(host)
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        for source_id, label, attr, file_types in SOURCE_FILES:
            source = registry.get(source_id)
            if source is None or not hasattr(source, attr):
                continue
            current = getattr(source, attr, None)
            field = QLineEdit(str(current or self.settings.value(f"sources/{source_id}/path", "")))
            field.setPlaceholderText(f"Selecione arquivo de dados ({file_types})")
            self.path_fields[source_id] = field
            if str(field.text()).strip():
                setattr(source, attr, Path(field.text()).expanduser())
            browse = QPushButton("Selecionar…")
            browse.clicked.connect(lambda checked=False, f=field, t=file_types: self._browse(f, t))
            row = QHBoxLayout()
            row.addWidget(field, 1)
            row.addWidget(browse)
            form.addRow(label, row)

        geosampa = registry.get("geosampa")
        saved_geosampa_endpoint = str(
            self.settings.value("sources/geosampa/endpoint", "") or ""
        ).strip()
        # Migrate the previous built-in default to the exact endpoint exercised
        # by the GeoSampa adapter and live integration test. Keep user-supplied
        # custom endpoints unchanged.
        legacy_default = "https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/ows"
        if not saved_geosampa_endpoint or saved_geosampa_endpoint.rstrip("/") == legacy_default:
            saved_geosampa_endpoint = getattr(geosampa, "endpoint", DEFAULT_WFS_URL)
        self.geosampa_url = QLineEdit(saved_geosampa_endpoint)
        geosampa_row = QHBoxLayout()
        geosampa_row.addWidget(self.geosampa_url, 1)
        geosampa_test = QPushButton("Testar conexão")
        geosampa_test.clicked.connect(self._test_geosampa)
        self._municipal_probe_buttons["sao_paulo"] = geosampa_test
        geosampa_row.addWidget(geosampa_test)
        form.addRow("GeoSampa — endpoint WFS", geosampa_row)
        geo_result = QLabel("Não testada nesta sessão — somente São Paulo capital")
        geo_result.setObjectName("muted")
        geo_result.setWordWrap(True)
        self._municipal_probe_labels["sao_paulo"] = geo_result
        form.addRow(geo_result)

        # Display the exact municipal service URLs used by the city/state-routed
        # adapter. They are read-only here so the UI cannot silently diverge from
        # the endpoint actually called by the adapter.
        municipal_title = QLabel("Fontes cadastrais municipais por localidade")
        municipal_title.setStyleSheet("font-size:16px;font-weight:800;margin-top:12px;")
        form.addRow(municipal_title)
        municipal_help = QLabel(
            "A pesquisa escolhe a fonte pelo município e UF do endereço. "
            "São Paulo capital usa exclusivamente GeoSampa; as demais localidades "
            "usam seus próprios serviços listados abaixo. Testar conexão verifica "
            "a resposta do serviço, não garante que todo endereço tenha cadastro."
        )
        municipal_help.setWordWrap(True)
        municipal_help.setObjectName("muted")
        form.addRow(municipal_help)
        self.municipal_endpoint_rows = {}
        for item in MUNICIPAL_SOURCE_ENDPOINTS:
            endpoint_field = QLineEdit(item["url"])
            endpoint_field.setReadOnly(True)
            endpoint_field.setToolTip(item["url"])
            self.municipal_endpoint_rows[item["id"]] = endpoint_field
            open_button = QPushButton("Abrir fonte")
            open_button.clicked.connect(
                lambda checked=False, url=item["url"]: self._open_source_url(url)
            )
            test_button = QPushButton("Testar conexão")
            test_button.clicked.connect(
                lambda checked=False, source=item: self._test_municipal_source(source)
            )
            row = QHBoxLayout()
            row.addWidget(endpoint_field, 1)
            row.addWidget(open_button)
            row.addWidget(test_button)
            self._municipal_probe_buttons[item["id"]] = test_button
            form.addRow(item["label"], row)
            layer_label = QLabel(
                f"Serviço/camada: {item['layer']}  •  Limite: {item['limits']}"
            )
            layer_label.setWordWrap(True)
            layer_label.setObjectName("muted")
            form.addRow(layer_label)
            status_text = (
                "Indisponibilidade relatada; testar para atualizar a conexão"
                if item["id"] == "bertioga" else
                "Não testada nesta sessão · apenas conectividade, não SQL/IPTU"
            )
            status_label = QLabel(status_text)
            status_label.setObjectName("muted")
            status_label.setWordWrap(True)
            self._municipal_probe_labels[item["id"]] = status_label
            form.addRow(status_label)

        # User-added municipal endpoints and authorized municipal exports are
        # stored separately from the built-in governmental integrations.
        custom_section = QWidget()
        custom_layout = QVBoxLayout(custom_section)
        custom_layout.setContentsMargins(0, 12, 0, 10)
        custom_title = QLabel("Minhas fontes municipais")
        custom_title.setStyleSheet("font-size:16px;font-weight:800;")
        custom_layout.addWidget(custom_title)
        custom_info = QLabel(
            "Adicione por município e UF, informe um link HTTPS público ou importe "
            "CSV, Excel, JSON ou GeoJSON de sua prefeitura. Sites sem API ficam "
            "somente como referência; WFS e ArcGIS são consultados por localidade."
        )
        custom_info.setObjectName("muted")
        custom_info.setWordWrap(True)
        custom_layout.addWidget(custom_info)
        add_custom = QPushButton("+ Adicionar fonte municipal")
        add_custom.setObjectName("primary")
        add_custom.clicked.connect(self._add_custom_source)
        custom_layout.addWidget(add_custom)
        self._custom_list_host = QWidget()
        self._custom_list_layout = QVBoxLayout(self._custom_list_host)
        self._custom_list_layout.setContentsMargins(0, 0, 0, 0)
        self._custom_list_layout.setSpacing(8)
        custom_layout.addWidget(self._custom_list_host)
        form.addRow(custom_section)
        self._refresh_custom_sources()

        # Bertioga downloads are three complementary layers, not three
        # independent address APIs. One atomic import builds the local index.
        bertioga_panel = QWidget()
        bertioga_box = QVBoxLayout(bertioga_panel)
        bertioga_box.setContentsMargins(2, 10, 2, 10)
        bertioga_title = QLabel("Bertioga/SP — lotes, vias e zoneamento (offline)")
        bertioga_title.setStyleSheet("font-size:16px;font-weight:800;color:#72f59e;")
        bertioga_box.addWidget(bertioga_title)
        bertioga_note = QLabel(
            "Importe os três GeoJSON oficiais do Geoportal de Bertioga. "
            "Os polígonos, inscrição do lote, quadra, lote, matrícula e zona "
            "ficam indexados somente neste computador. Rua + emplacamento "
            "produzem candidatos cartográficos, não SQL/IPTU confirmado."
        )
        bertioga_note.setWordWrap(True)
        bertioga_note.setObjectName("muted")
        bertioga_box.addWidget(bertioga_note)
        self._bertioga_status = QLabel(self._bertioga_source_status())
        self._bertioga_status.setWordWrap(True)
        self._bertioga_status.setObjectName("muted")
        bertioga_box.addWidget(self._bertioga_status)
        self._bertioga_import_button = QPushButton(
            "Importar 3 GeoJSON de Bertioga (lotes, eixos e zoneamento)"
        )
        self._bertioga_import_button.clicked.connect(self._start_bertioga_import)
        bertioga_box.addWidget(self._bertioga_import_button)
        form.addRow(bertioga_panel)

        recife_panel = QWidget()
        recife_box = QVBoxLayout(recife_panel)
        recife_box.setContentsMargins(2, 10, 2, 10)
        recife_title = QLabel("Recife/PE — dados abertos IPTU CSV (offline)")
        recife_title.setStyleSheet("font-size:16px;font-weight:800;color:#72f59e;")
        recife_box.addWidget(recife_title)
        recife_note = QLabel(
            "Selecione um ou mais CSVs anuais oficiais (2025 e 2026, por exemplo). "
            "São armazenados somente endereço, complemento, área, uso e coordenadas "
            "no computador. CPF/CNPJ, identificadores de contribuinte e tributos "
            "não são importados. Rua/número fornecem candidatos, não inscrição IPTU."
        )
        recife_note.setWordWrap(True)
        recife_note.setObjectName("muted")
        recife_box.addWidget(recife_note)
        self._recife_status = QLabel(self._recife_source_status())
        self._recife_status.setWordWrap(True)
        self._recife_status.setObjectName("muted")
        recife_box.addWidget(self._recife_status)
        self._recife_import_button = QPushButton("Importar CSVs anuais do Recife")
        self._recife_import_button.clicked.connect(self._start_recife_import)
        recife_box.addWidget(self._recife_import_button)
        form.addRow(recife_panel)

        sinter = registry.get("sinter_cib")
        self.sinter_url = QLineEdit(
            str(getattr(sinter, "api_base_url", "") or self.settings.value("sources/sinter_cib/api_base_url", ""))
        )
        self.sinter_url.setPlaceholderText("URL-base oficial fornecida ao seu órgão/conta")
        form.addRow("SINTER/CIB — URL autorizada", self.sinter_url)
        self.sinter_token = QLineEdit()
        self.sinter_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.sinter_token.setPlaceholderText("Token de acesso autorizado")
        sinter_token_row = QHBoxLayout()
        sinter_token_row.addWidget(self.sinter_token, 1)
        sinter_clear_token = QPushButton("Remover token salvo")
        sinter_clear_token.clicked.connect(
            lambda checked=False: self._clear_saved_token(
                "sinter_cib_api_token", self.sinter_token, "sinter_cib"
            )
        )
        sinter_token_row.addWidget(sinter_clear_token)
        form.addRow("SINTER/CIB — token", sinter_token_row)

        municipal_wfs = registry.get("municipal_wfs")
        self.wfs_fields = {}
        wfs_definitions = (
            ("endpoint", "Endpoint WFS municipal", "https://servicos.exemplo.gov.br/geoserver/ows"),
            ("layer", "Camada WFS", "workspace:camada"),
            ("address_field", "Campo de logradouro", "logradouro"),
            ("number_field", "Campo de número", "numero"),
            ("block_field", "Campo de quadra", "quadra"),
            ("lot_field", "Campo de lote", "lote"),
            ("area_field", "Campo de área (m²)", "area_m2"),
            ("id_field", "Campo identificador", "id"),
        )
        for key, label, placeholder in wfs_definitions:
            field = QLineEdit(str(
                getattr(municipal_wfs, key, "") or
                self.settings.value(f"sources/municipal_wfs/{key}", "")
            ))
            field.setPlaceholderText(placeholder)
            self.wfs_fields[key] = field
            form.addRow(label, field)

        self.wfs_token = QLineEdit()
        self.wfs_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.wfs_token.setPlaceholderText("Bearer token autorizado, se necessário")
        wfs_token_row = QHBoxLayout()
        wfs_token_row.addWidget(self.wfs_token, 1)
        wfs_clear_token = QPushButton("Remover token salvo")
        wfs_clear_token.clicked.connect(
            lambda checked=False: self._clear_saved_token(
                "municipal_wfs_api_token", self.wfs_token, "municipal_wfs"
            )
        )
        wfs_token_row.addWidget(wfs_clear_token)
        form.addRow("WFS municipal — token", wfs_token_row)

        self.inde_endpoint = QLineEdit(str(
            self.settings.value("sources/inde/csw_endpoint", "https://metadados.inde.gov.br/geonetwork/srv/por/csw")
        ))
        self.inde_endpoint.setPlaceholderText("Endpoint CSW oficial da INDE")
        form.addRow("INDE — endpoint CSW online", self.inde_endpoint)

        self.inde_query = QLineEdit()
        self.inde_query.setPlaceholderText("Ex.: cadastro imobiliário, uso do solo, limites municipais")
        inde_search_button = QPushButton("Pesquisar no catálogo online")
        inde_search_button.clicked.connect(self._search_inde_online)
        inde_search_row = QHBoxLayout()
        inde_search_row.addWidget(self.inde_query, 1)
        inde_search_row.addWidget(inde_search_button)
        form.addRow("INDE — descobrir geosserviços", inde_search_row)

        inde_path = QLineEdit(str(self.settings.value("sources/inde/catalog_path", "")))
        inde_path.setPlaceholderText("Catálogo INDE autorizado local (CSV/JSON)")
        self.inde_catalog_path = inde_path
        inde_browse = QPushButton("Selecionar catálogo INDE…")
        inde_browse.clicked.connect(
            lambda checked=False, f=inde_path: self._browse(f, "CSV ou JSON")
        )
        inde_row = QHBoxLayout()
        inde_row.addWidget(inde_path, 1)
        inde_row.addWidget(inde_browse)
        inde_list = QPushButton("Listar serviços")
        inde_list.clicked.connect(self._show_inde_catalog)
        inde_row.addWidget(inde_list)
        form.addRow("Catálogo de geosserviços INDE", inde_row)

        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        note = QLabel(
            "Segurança: tokens não são gravados em texto simples nas configurações. "
            "Para persistência, o aplicativo tenta usar o cofre de credenciais do sistema. "
            "Se o cofre não estiver disponível, o token vale somente até fechar o aplicativo."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        root.addWidget(note)

        buttons = QHBoxLayout()
        validate = QPushButton("Validar configurações")
        validate.clicked.connect(self._validate)
        buttons.addWidget(validate)
        buttons.addStretch()
        save = QPushButton("Salvar configurações")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        close = QPushButton("Fechar")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self._load_saved_token()
        # Keep action buttons above the Windows taskbar. The source catalogue
        # scrolls independently; the save/close row always remains accessible.
        fit_window_to_screen(self, QSize(820, 720), QSize(480, 360))

    def _search_inde_online(self) -> None:
        query = self.inde_query.text().strip()
        endpoint = self.inde_endpoint.text().strip()
        try:
            from .sources.inde import INDECatalog
            services = INDECatalog.search_remote(query, endpoint)
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Catálogo INDE", str(exc))
            return
        self.settings.setValue("sources/inde/csw_endpoint", endpoint)
        if not services:
            QMessageBox.information(
                self, "Catálogo INDE",
                "A pesquisa online não retornou metadados para esse termo. Tente outra palavra-chave."
            )
            return
        lines = [
            f"{item.title} | {item.service_type or 'tipo de serviço não identificado'}"
            f"\nResponsável: {item.provider or 'não informado'}"
            f"\nURL: {item.url or 'não informada'}"
            f"\nID: {item.service_id}"
            for item in services[:50]
        ]
        suffix = f"\n\nExibindo 50 de {len(services)} registros." if len(services) > 50 else ""
        QMessageBox.information(
            self, f"Resultados INDE ({len(services)})",
            "\n\n".join(lines) + suffix
        )

    def _show_inde_catalog(self) -> None:
        path = Path(self.inde_catalog_path.text().strip()).expanduser()
        if not path.is_file():
            QMessageBox.information(
                self, "Catálogo INDE",
                "Selecione um catálogo INDE em CSV/JSON obtido de uma fonte autorizada."
            )
            return
        try:
            from .sources.inde import INDECatalog
            services = INDECatalog(path).load()
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Catálogo INDE", f"Não foi possível ler o catálogo: {exc}")
            return
        if not services:
            QMessageBox.information(self, "Catálogo INDE", "O catálogo não contém geosserviços.")
            return
        lines = [
            f"{item.title} | {item.service_type or 'tipo não informado'}"
            f"\nCamada: {item.layer or 'não informada'}"
            f"\nURL: {item.url or 'não informada'}"
            for item in services[:80]
        ]
        suffix = f"\n\nExibindo 80 de {len(services)} serviços." if len(services) > 80 else ""
        QMessageBox.information(
            self, f"Serviços INDE ({len(services)})",
            "\n\n".join(lines) + suffix
        )

    def _browse(self, field: QLineEdit, file_types: str) -> None:
        if "ZIP" in file_types and "CSV" in file_types:
            patterns = "Dados (*.csv *.zip *.json *.geojson)"
        elif "JSONL" in file_types:
            patterns = "Dados (*.csv *.json *.geojson *.jsonl)"
        elif "CSV ou JSON" in file_types:
            patterns = "Dados (*.csv *.json)"
        else:
            patterns = "Dados (*.csv *.json *.geojson)"
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar base local", field.text(), patterns)
        if path:
            field.setText(path)

    def _clear_saved_token(self, key: str, field: QLineEdit, source_id: str) -> None:
        """Explicitly remove a saved credential and clear it from the active adapter."""
        try:
            import keyring
            try:
                keyring.delete_password("ImobHunter-BR", key)
            except keyring.errors.PasswordDeleteError:
                # No stored secret is already the requested end state.
                pass
        except Exception as exc:  # noqa: BLE001 - keyring backends vary by platform.
            QMessageBox.warning(
                self,
                "Cofre de credenciais",
                "Não foi possível remover a credencial salva pelo sistema. "
                f"Detalhe: {type(exc).__name__}: {exc}",
            )
            return
        field.clear()
        source = self.registry.get(source_id)
        if source is not None and hasattr(source, "api_token"):
            source.api_token = ""
        QMessageBox.information(
            self, "Credencial removida",
            "O token foi removido do cofre e da sessão atual."
        )

    def _load_saved_token(self) -> None:
        try:
            import keyring
            token = keyring.get_password("ImobHunter-BR", "sinter_cib_api_token") or ""
            self.sinter_token.setText(token)
            sinter = self.registry.get("sinter_cib")
            if sinter is not None:
                sinter.api_token = token
            wfs = self.registry.get("municipal_wfs")
            wfs_token = keyring.get_password("ImobHunter-BR", "municipal_wfs_api_token") or ""
            self.wfs_token.setText(wfs_token)
            if wfs is not None:
                wfs.api_token = wfs_token
        except Exception:  # noqa: BLE001 - keyring backends expose different exception types.
            # Missing/unavailable OS keyring is expected on some portable systems.
            self.sinter_token.clear()

    def _save_token(self, token: str) -> bool:
        try:
            import keyring
            if token:
                keyring.set_password("ImobHunter-BR", "sinter_cib_api_token", token)
            else:
                keyring.delete_password("ImobHunter-BR", "sinter_cib_api_token")
            return True
        except Exception:  # noqa: BLE001 - keyring backend errors vary by platform.
            return False


    def _open_source_url(self, url: str) -> None:
        import webbrowser
        webbrowser.open(url)

    def _refresh_custom_sources(self) -> None:
        layout = self._custom_list_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for key in tuple(self._municipal_probe_buttons):
            if key.startswith("local_municipal_"):
                self._municipal_probe_buttons.pop(key, None)
                self._municipal_probe_labels.pop(key, None)
        try:
            entries = self.custom_store.list()
        except (ValueError, OSError, TypeError) as exc:
            warning = QLabel(f"Não foi possível ler fontes salvas: {exc}")
            warning.setWordWrap(True)
            layout.addWidget(warning)
            return
        if not entries:
            note = QLabel("Nenhuma fonte municipal personalizada adicionada.")
            note.setObjectName("muted")
            layout.addWidget(note)
        for source in entries:
            container = QWidget()
            box = QVBoxLayout(container)
            box.setContentsMargins(3, 6, 3, 6)
            header = QLabel(f"{source.name} · {source.city}/{source.state}")
            header.setStyleSheet("font-weight:750;color:#72f59e")
            box.addWidget(header)
            endpoint = QLineEdit(
                source.url or "Fonte local — sem link cadastrado"
            )
            endpoint.setReadOnly(True)
            endpoint.setToolTip(source.url)
            box.addWidget(endpoint)
            actions = QHBoxLayout()
            source_id = source.source_id
            if source.url:
                test_button = QPushButton("Testar fonte")
                details = {
                    "id": source_id, "url": source.url, "kind": source.kind,
                    "custom": "true",
                }
                test_button.clicked.connect(
                    lambda checked=False, item=details: self._test_municipal_source(item)
                )
                self._municipal_probe_buttons[source_id] = test_button
                actions.addWidget(test_button)
            file_button = QPushButton("Importar arquivo")
            file_button.clicked.connect(
                lambda checked=False, sid=source_id: self._import_custom_file(sid)
            )
            actions.addWidget(file_button)
            remove_button = QPushButton("Remover fonte")
            remove_button.clicked.connect(
                lambda checked=False, sid=source_id: self._remove_custom_source(sid)
            )
            actions.addWidget(remove_button)
            box.addLayout(actions)
            stored_file = self.custom_store.local_path(source)
            status = QLabel(
                f"Arquivo local: {stored_file.name}" if stored_file and stored_file.is_file()
                else "Sem arquivo municipal importado."
            )
            status.setObjectName("muted")
            status.setWordWrap(True)
            box.addWidget(status)
            if source.url:
                check_status = QLabel(
                    "Não testada nesta sessão — conexão não confirma SQL/IPTU."
                )
                check_status.setObjectName("muted")
                check_status.setWordWrap(True)
                self._municipal_probe_labels[source_id] = check_status
                box.addWidget(check_status)
            layout.addWidget(container)
        layout.addStretch(1)

    def _add_custom_source(self) -> None:
        editor = QDialog(self)
        editor.setWindowTitle("Adicionar nova fonte municipal")
        editor.setMinimumWidth(360)
        edit_layout = QVBoxLayout(editor)
        form = QFormLayout()
        name_field = QLineEdit()
        name_field.setPlaceholderText("Ex.: Geoportal cadastral")
        city_field = QLineEdit()
        city_field.setPlaceholderText("Ex.: Bertioga")
        state_field = QLineEdit()
        state_field.setPlaceholderText("UF: SP")
        state_field.setMaxLength(2)
        url_field = QLineEdit()
        url_field.setPlaceholderText("https://prefeitura... (opcional para arquivo local)")
        protocol = QComboBox()
        protocol.addItem("Detectar pelo link", "auto")
        protocol.addItem("WFS (serviço de camadas)", "wfs")
        protocol.addItem("ArcGIS REST (camada /0)", "arcgis")
        protocol.addItem("Site da prefeitura (somente referência)", "website")
        form.addRow("Nome da fonte", name_field)
        form.addRow("Município", city_field)
        form.addRow("UF", state_field)
        form.addRow("Link HTTPS", url_field)
        form.addRow("Tipo de serviço", protocol)
        edit_layout.addLayout(form)
        notice = QLabel(
            "Se o link for apenas um site, ele será salvo e poderá ser testado; "
            "para consultas automáticas escolha WFS ou ArcGIS com endpoint válido. "
            "É possível cadastrar sem link e importar arquivos locais depois."
        )
        notice.setWordWrap(True)
        edit_layout.addWidget(notice)
        commands = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        commands.button(QDialogButtonBox.StandardButton.Save).setText("Salvar fonte")
        commands.accepted.connect(editor.accept)
        commands.rejected.connect(editor.reject)
        edit_layout.addWidget(commands)
        fit_window_to_screen(editor, QSize(550, 430), QSize(360, 300))
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        kind = str(protocol.currentData())
        url = url_field.text().strip()
        if kind == "auto":
            kind = infer_protocol(url)
        try:
            source = self.custom_store.add(
                name_field.text(), city_field.text(), state_field.text(),
                url=url, kind=kind,
            )
            reload_custom_sources(self.registry, self.custom_store)
        except (ValueError, TypeError, OSError) as exc:
            QMessageBox.warning(self, "Fonte municipal", str(exc))
            return
        self._refresh_custom_sources()
        QMessageBox.information(
            self, "Fonte municipal salva",
            f"{source.name} — {source.city}/{source.state} foi adicionada. "
            "Use Testar fonte e/ou Importar arquivo para habilitar os dados.",
        )

    def _bertioga_source_status(self) -> str:
        try:
            counts = self.bertioga_store.counts()
        except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
            return f"Base local de Bertioga com erro: {type(exc).__name__}."
        if not counts:
            return "Não instalada — selecione lotes.geojson, eixoLogradouro.geojson e zoneamento.geojson."
        return (
            f"Base local instalada: {counts['lotes']:,} lotes, "
            f"{counts['logradouros']:,} eixos e {counts['zonas']:,} zonas. "
            "Não depende do WFS online da prefeitura."
        )

    def _start_bertioga_import(self) -> None:
        if self._bertioga_import_worker is not None:
            return
        selected = []
        for label in (
            "1/3 — lotes.geojson (inscrição, quadra, lote e matrícula)",
            "2/3 — eixoLogradouro.geojson (ruas e CEP)",
            "3/3 — zoneamento.geojson (zonas e usos)",
        ):
            file_path, _ = QFileDialog.getOpenFileName(
                self, f"Bertioga — selecionar {label}", "",
                "Arquivos GeoJSON (*.geojson *.json)",
            )
            if not file_path:
                return
            selected.append(Path(file_path))
        self._bertioga_import_button.setEnabled(False)
        self._bertioga_status.setText(
            "Importando e indexando as 3 camadas em SQLite local… "
            "A pesquisa de Bertioga continuará offline após concluir."
        )
        worker = BertiogaImportWorker(tuple(selected))
        self._bertioga_import_worker = worker
        worker.signals.finished.connect(self._finish_bertioga_import)
        QThreadPool.globalInstance().start(worker)

    def _finish_bertioga_import(self, result: object) -> None:
        self._bertioga_import_worker = None
        self._bertioga_import_button.setEnabled(True)
        if not isinstance(result, dict) or not result.get("ok"):
            message = result.get("message", "Erro de importação") if isinstance(result, dict) \
                else "Erro ao importar os arquivos GeoJSON"
            self._bertioga_status.setText("Falha: " + str(message))
            QMessageBox.warning(self, "Bertioga — importação", str(message))
            return
        self._bertioga_status.setText(self._bertioga_source_status())
        QMessageBox.information(
            self, "Bertioga — camadas locais",
            "As 3 camadas foram indexadas neste computador. "
            "O ImobHunter usará esse pacote na próxima pesquisa por "
            "endereço em Bertioga/SP, preservando as inscrições "
            "como dados de lotes candidatos até confirmação de vínculo fiscal.",
        )

    def _recife_source_status(self) -> str:
        try:
            counts = self.recife_store.counts()
        except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
            return f"Base local do Recife com erro: {type(exc).__name__}."
        if not counts:
            return "Não instalada — selecione os CSVs anuais oficiais do Recife."
        summary = ", ".join(f"{year}: {count:,} registros" for year, count in sorted(counts.items()))
        return f"Base local de Recife instalada: {summary}. Pesquisa offline."

    def _start_recife_import(self) -> None:
        if self._recife_import_worker is not None:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Recife — selecionar um ou mais CSVs de IPTU", "",
            "Arquivos CSV (*.csv)",
        )
        if not paths:
            return
        self._recife_import_button.setEnabled(False)
        self._recife_status.setText("Indexando os CSVs em SQLite local, sem enviar dados à nuvem…")
        worker = RecifeIPTUImportWorker(tuple(Path(path) for path in paths))
        self._recife_import_worker = worker
        worker.signals.finished.connect(self._finish_recife_import)
        QThreadPool.globalInstance().start(worker)

    def _finish_recife_import(self, result: object) -> None:
        self._recife_import_worker = None
        self._recife_import_button.setEnabled(True)
        if not isinstance(result, dict) or not result.get("ok"):
            message = result.get("message", "Falha de importação") if isinstance(result, dict) \
                else "Falha ao importar os arquivos."
            self._recife_status.setText("Falha: " + str(message))
            QMessageBox.warning(self, "Recife — importação", str(message))
            return
        self._recife_status.setText(self._recife_source_status())
        QMessageBox.information(
            self, "Recife — cadastro local",
            "Os CSVs foram indexados neste computador. Se o serviço cadastral "
            "ESIG não retornar um imóvel exato, a pesquisa poderá usar o "
            "exercício local mais recente, sem inventar SQL/IPTU.",
        )

    def _import_custom_file(self, source_id: str) -> None:
        source = self.custom_store.get(source_id)
        if source is None:
            QMessageBox.warning(self, "Arquivo municipal", "Fonte não encontrada.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, f"Importar dados de {source.city}/{source.state}", "",
            "Arquivos municipais (*.csv *.xlsx *.json *.geojson)",
        )
        if not path:
            return
        try:
            updated, count = self.custom_store.import_file(source_id, Path(path))
            reload_custom_sources(self.registry, self.custom_store)
        except (ValueError, OSError, TypeError) as exc:
            QMessageBox.warning(self, "Importação municipal", str(exc))
            return
        self._refresh_custom_sources()
        QMessageBox.information(
            self, "Arquivo importado",
            f"{count} linhas importadas para {updated.city}/{updated.state}. "
            "Os registros serão filtrados por endereço ou quadra/lote nas próximas pesquisas.",
        )

    def _remove_custom_source(self, source_id: str) -> None:
        source = self.custom_store.get(source_id)
        if source is None:
            return
        answer = QMessageBox.question(
            self, "Remover fonte municipal",
            f"Remover '{source.name}' de {source.city}/{source.state} e "
            "sua cópia local do arquivo cadastral? O original não será apagado.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.custom_store.remove(source_id)
            reload_custom_sources(self.registry, self.custom_store)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Remover fonte", str(exc))
            return
        self._refresh_custom_sources()

    def _test_municipal_source(self, source: dict[str, str]) -> None:
        source_id = source["id"]
        if source_id in self._municipal_probe_workers:
            return
        button = self._municipal_probe_buttons[source_id]
        status_label = self._municipal_probe_labels[source_id]
        button.setEnabled(False)
        status_label.setText("Consultando metadados da fonte oficial…")
        worker = MunicipalProbeWorker(source)
        self._municipal_probe_workers[source_id] = worker
        worker.signals.finished.connect(self._municipal_probe_finished)
        QThreadPool.globalInstance().start(worker)

    def _municipal_probe_finished(
        self, source_id: str, result: EndpointProbe
    ) -> None:
        self._municipal_probe_workers.pop(source_id, None)
        button = self._municipal_probe_buttons.get(source_id)
        label = self._municipal_probe_labels.get(source_id)
        if button is not None:
            button.setEnabled(True)
        if label is None:
            return
        if result.state == "responded":
            label.setText(
                f"Metadados acessíveis ({result.latency_ms} ms). "
                f"{result.message}. Não confirma SQL/IPTU, lotes ou proprietário."
            )
            label.setStyleSheet("color:#61ee8d;")
        elif result.state == "timeout":
            label.setText(
                f"Tempo limite excedido ({result.latency_ms} ms): "
                f"{result.message}. Serviço não confirmado; imóvel não foi descartado."
            )
            label.setStyleSheet("color:#f1bb7c;")
        else:
            label.setText(
                f"Fonte indisponível ou resposta inválida ({result.latency_ms} ms): "
                f"{result.message}. Não significa que o imóvel não exista."
            )
            label.setStyleSheet("color:#f1bb7c;")

    def _test_geosampa(self) -> None:
        item = next(
            item for item in settings_endpoint_rows()
            if item["id"] == "sao_paulo"
        )
        source = {**item, "url": self.geosampa_url.text().strip()}
        self._test_municipal_source(source)

    def _validate(self) -> None:
        problems: list[str] = []
        for source_id, field in self.path_fields.items():
            value = field.text().strip()
            if value and not Path(value).expanduser().is_file():
                problems.append(f"{source_id}: arquivo não encontrado — {value}")
        if not is_official_service_url(self.geosampa_url.text().strip()):
            problems.append("GeoSampa: informe um endpoint HTTPS oficial gov.br.")
        sinter_url = self.sinter_url.text().strip()
        if sinter_url and (urlparse(sinter_url).scheme not in {"http", "https"} or not urlparse(sinter_url).netloc):
            problems.append("SINTER/CIB: URL-base inválida.")
        wfs_endpoint = self.wfs_fields["endpoint"].text().strip()
        wfs_layer = self.wfs_fields["layer"].text().strip()
        if bool(wfs_endpoint) != bool(wfs_layer):
            problems.append("WFS municipal: informe endpoint e camada juntos.")
        if wfs_endpoint and (urlparse(wfs_endpoint).scheme not in {"http", "https"} or not urlparse(wfs_endpoint).netloc):
            problems.append("WFS municipal: endpoint HTTP/HTTPS inválido.")
        catalog_path = self.inde_catalog_path.text().strip()
        if catalog_path and not Path(catalog_path).expanduser().is_file():
            problems.append("INDE: arquivo de catálogo não encontrado.")
        if sinter_url and not (self.sinter_token.text().strip() or self._existing_token()):
            problems.append("SINTER/CIB: URL preenchida, mas falta o token autorizado.")
        if problems:
            QMessageBox.warning(self, "Validação", "\n".join(problems))
        else:
            QMessageBox.information(
                self, "Validação local",
                "Os caminhos e formatos básicos foram validados. Isso não comprova autorização "
                "nem garante que um serviço remoto aceite a consulta; use a pesquisa e o status "
                "das fontes para confirmar o funcionamento real."
            )

    def _existing_wfs_token(self) -> str:
        try:
            import keyring
            return keyring.get_password("ImobHunter-BR", "municipal_wfs_api_token") or ""
        except Exception:  # noqa: BLE001 - keyring backend errors vary by platform.
            return ""

    def _existing_token(self) -> str:
        try:
            import keyring
            return keyring.get_password("ImobHunter-BR", "sinter_cib_api_token") or ""
        except Exception:  # noqa: BLE001 - keyring backend errors vary by platform.
            return ""

    def _save(self) -> None:
        problems = []
        catalog_path = self.inde_catalog_path.text().strip()
        if catalog_path and not Path(catalog_path).expanduser().is_file():
            problems.append("INDE: arquivo de catálogo não encontrado.")
        wfs_endpoint = self.wfs_fields["endpoint"].text().strip()
        wfs_layer = self.wfs_fields["layer"].text().strip()
        if bool(wfs_endpoint) != bool(wfs_layer):
            problems.append("WFS municipal: informe endpoint e camada juntos.")
        if wfs_endpoint and (urlparse(wfs_endpoint).scheme not in {"http", "https"} or not urlparse(wfs_endpoint).netloc):
            problems.append("WFS municipal: endpoint HTTP/HTTPS inválido.")
        if not is_official_service_url(self.geosampa_url.text().strip()):
            problems.append("GeoSampa: apenas endpoint HTTPS oficial gov.br.")
        for source_id, field in self.path_fields.items():
            value = field.text().strip()
            if value and not Path(value).expanduser().is_file():
                problems.append(f"{source_id}: arquivo não encontrado — {value}")
        if problems:
            QMessageBox.warning(self, "Não foi possível salvar", "\n".join(problems))
            return

        for source_id, field in self.path_fields.items():
            value = field.text().strip()
            self.settings.setValue(f"sources/{source_id}/path", value)
            source = self.registry.get(source_id)
            if source is not None and hasattr(source, "data_path"):
                source.data_path = Path(value).expanduser() if value else None

        endpoint = self.geosampa_url.text().strip().rstrip("/")
        self.settings.setValue("sources/geosampa/endpoint", endpoint)
        geosampa = self.registry.get("geosampa")
        if geosampa is not None and endpoint:
            geosampa.endpoint = endpoint

        sinter_url = self.sinter_url.text().strip().rstrip("/")
        self.settings.setValue("sources/sinter_cib/api_base_url", sinter_url)
        sinter = self.registry.get("sinter_cib")
        if sinter is not None:
            sinter.api_base_url = sinter_url
            sinter.api_token = self.sinter_token.text().strip() or self._existing_token()

        token = self.sinter_token.text().strip()
        token_saved = self._save_token(token) if token else True

        wfs = self.registry.get("municipal_wfs")
        for key, field in self.wfs_fields.items():
            value = field.text().strip()
            self.settings.setValue(f"sources/municipal_wfs/{key}", value)
            if wfs is not None and hasattr(wfs, key):
                setattr(wfs, key, value)
        self.settings.setValue("sources/inde/catalog_path", catalog_path)
        self.settings.setValue("sources/inde/csw_endpoint", self.inde_endpoint.text().strip())
        self.settings.sync()
        wfs_token = self.wfs_token.text().strip()
        wfs_token_saved = True
        if wfs_token:
            try:
                import keyring
                keyring.set_password("ImobHunter-BR", "municipal_wfs_api_token", wfs_token)
            except Exception:  # noqa: BLE001 - keyring backend errors vary by platform.
                wfs_token_saved = False
        wfs = self.registry.get("municipal_wfs")
        if wfs is not None:
            wfs.api_token = wfs_token or self._existing_wfs_token()
        if (token and not token_saved) or (wfs_token and not wfs_token_saved):
            QMessageBox.warning(
                self, "Token não persistido",
                "As demais configurações foram salvas, mas o cofre de credenciais do sistema "
                "não está disponível. Um ou mais tokens permanecem apenas nesta sessão."
            )
        QMessageBox.information(self, "Configurações salvas", "As configurações foram aplicadas à pesquisa nesta sessão.")
        self.accept()



def apply_saved_source_settings(registry) -> None:
    """Apply per-user paths and endpoints before the first search of a new session."""
    settings = QSettings("ImobHunter", "ImobHunter-BR")
    for source_id, _label, attr, _file_types in SOURCE_FILES:
        source = registry.get(source_id)
        if source is None or not hasattr(source, attr):
            continue
        value = str(settings.value(f"sources/{source_id}/path", "") or "").strip()
        if value:
            source.data_path = Path(value).expanduser()

    geosampa = registry.get("geosampa")
    if geosampa is not None:
        endpoint = str(settings.value("sources/geosampa/endpoint", "") or "").strip()
        if endpoint and is_official_service_url(endpoint):
            geosampa.endpoint = endpoint

    sinter = registry.get("sinter_cib")
    if sinter is not None:
        endpoint = str(settings.value("sources/sinter_cib/api_base_url", "") or "").strip()
        if endpoint:
            sinter.api_base_url = endpoint
        try:
            import keyring
            sinter.api_token = keyring.get_password("ImobHunter-BR", "sinter_cib_api_token") or ""
        except Exception:  # noqa: BLE001 - keyring backend errors vary by platform.
            sinter.api_token = ""

    wfs = registry.get("municipal_wfs")
    if wfs is not None:
        for key in ("endpoint", "layer", "address_field", "number_field", "block_field", "lot_field", "area_field", "id_field"):
            value = str(settings.value(f"sources/municipal_wfs/{key}", "") or "").strip()
            if value:
                setattr(wfs, key, value)
        try:
            import keyring
            wfs.api_token = keyring.get_password("ImobHunter-BR", "municipal_wfs_api_token") or ""
        except Exception:  # noqa: BLE001 - keyring backend errors vary by platform.
            wfs.api_token = ""

    # The per-user catalogue persists independently of QSettings, and each
    # user-added source is registered only for its own municipality and UF.
    try:
        reload_custom_sources(registry, CustomMunicipalStore())
    except (OSError, ValueError, TypeError):
        # A damaged user catalogue must never prevent access to built-in
        # municipal sources or the licence activation window. The settings
        # dialog will show the catalogue error so the user can repair it.
        pass
