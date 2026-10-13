from __future__ import annotations

from pathlib import Path

import httpx
from urllib.parse import urlparse

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
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


class SourceSettingsDialog(QDialog):
    """Configures local datasets and supported source endpoints for this user."""

    def __init__(self, registry, parent=None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.settings = QSettings("ImobHunter", "ImobHunter-BR")
        self.path_fields: dict[str, QLineEdit] = {}
        self.setWindowTitle("Configurações de fontes e acessos")
        self.resize(820, 720)
        self.setMinimumSize(700, 560)
        self.setStyleSheet("""
            QDialog { background:#07111b; color:#eaf2f7; }
            QLabel { color:#eaf2f7; }
            QLabel#muted { color:#8da2b2; }
            QLineEdit { background:#0b1926; color:#f4f8fb; border:1px solid #254156; border-radius:7px; padding:8px; }
            QPushButton { background:#102332; color:#eaf2f7; border:1px solid #2b4c63; border-radius:8px; padding:8px 12px; }
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
        self.geosampa_url = QLineEdit(
            str(self.settings.value(
                "sources/geosampa/endpoint",
                getattr(geosampa, "endpoint", "https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/ows"),
            ))
        )
        geosampa_row = QHBoxLayout()
        geosampa_row.addWidget(self.geosampa_url, 1)
        geosampa_test = QPushButton("Testar conexão")
        geosampa_test.clicked.connect(self._test_geosampa)
        geosampa_row.addWidget(geosampa_test)
        form.addRow("GeoSampa — endpoint WFS", geosampa_row)

        sinter = registry.get("sinter_cib")
        self.sinter_url = QLineEdit(
            str(getattr(sinter, "api_base_url", "") or self.settings.value("sources/sinter_cib/api_base_url", ""))
        )
        self.sinter_url.setPlaceholderText("URL-base oficial fornecida ao seu órgão/conta")
        form.addRow("SINTER/CIB — URL autorizada", self.sinter_url)
        self.sinter_token = QLineEdit()
        self.sinter_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.sinter_token.setPlaceholderText("Token de acesso (opcional; não exibido novamente)")
        form.addRow("SINTER/CIB — token", self.sinter_token)

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
        self.wfs_token.setPlaceholderText("Bearer token, se o serviço exigir")
        form.addRow("WFS municipal — token", self.wfs_token)

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

    def _test_geosampa(self) -> None:
        endpoint = self.geosampa_url.text().strip()
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            QMessageBox.warning(self, "GeoSampa", "Informe um endpoint HTTP/HTTPS válido.")
            return
        try:
            response = httpx.get(
                endpoint,
                params={"service": "WFS", "version": "1.0.0", "request": "GetCapabilities"},
                timeout=12.0,
                follow_redirects=True,
            )
            response.raise_for_status()
            payload = response.text
        except httpx.HTTPError as exc:
            QMessageBox.warning(self, "GeoSampa", f"Falha na conexão WFS: {exc}")
            return
        if "WFS_Capabilities" not in payload:
            QMessageBox.warning(
                self, "GeoSampa",
                "O servidor respondeu, mas não retornou um documento WFS GetCapabilities válido."
            )
            return
        layer = "geoportal:lote_cidadao"
        if layer not in payload:
            QMessageBox.warning(
                self, "GeoSampa",
                f"Conexão WFS respondeu, mas a camada padrão {layer} não foi encontrada. "
                "Confirme o nome da camada antes de pesquisar."
            )
            return
        QMessageBox.information(
            self, "GeoSampa",
            f"Conexão WFS validada. Camada {layer} anunciada pelo servidor."
        )

    def _validate(self) -> None:
        problems: list[str] = []
        for source_id, field in self.path_fields.items():
            value = field.text().strip()
            if value and not Path(value).expanduser().is_file():
                problems.append(f"{source_id}: arquivo não encontrado — {value}")
        parsed = urlparse(self.geosampa_url.text().strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            problems.append("GeoSampa: informe uma URL HTTP/HTTPS válida.")
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
        if endpoint:
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
