from __future__ import annotations

from pathlib import Path

from urllib.parse import urlparse

from PySide6.QtCore import QSettings, QObject, QRunnable, QThreadPool, Signal
from .application.municipal_endpoints import settings_endpoint_rows
from .application.source_probe import EndpointProbe, is_official_service_url, probe_endpoint
from .sources.geosampa import DEFAULT_WFS_URL

from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
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


class SourceSettingsDialog(QDialog):
    """Configures local datasets and supported source endpoints for this user."""

    def __init__(self, registry, parent=None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.settings = QSettings("ImobHunter", "ImobHunter-BR")
        self.path_fields: dict[str, QLineEdit] = {}
        self._municipal_probe_workers: dict[str, MunicipalProbeWorker] = {}
        self._municipal_probe_buttons: dict[str, QPushButton] = {}
        self._municipal_probe_labels: dict[str, QLabel] = {}
        self.setWindowTitle("Configurações de fontes e acessos")
        self.resize(820, 720)
        self.setMinimumSize(700, 560)
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
        host = QWidget()
        form = QFormLayout(host)
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

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
