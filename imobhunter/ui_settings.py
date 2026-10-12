from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import httpx
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

SOURCE_FILES = (
    ("cnefe", "IBGE / CNEFE", "data_path", "CSV, ZIP, JSON ou GeoJSON"),
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
            browse = QPushButton("Selecionar…")
            browse.clicked.connect(lambda checked=False, f=field, t=file_types: self._browse(f, t))
            row = QHBoxLayout()
            row.addWidget(field, 1)
            row.addWidget(browse)
            form.addRow(label, row)

        geosampa = registry.get("geosampa")
        self.geosampa_url = QLineEdit(
            str(getattr(geosampa, "endpoint", "") or self.settings.value(
                "sources/geosampa/endpoint", "https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/ows"
            ))
        )
        form.addRow("GeoSampa — endpoint WFS", self.geosampa_url)

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
            self.sinter_token.setText(keyring.get_password("ImobHunter-BR", "sinter_cib_api_token") or "")
        except Exception:
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
        except Exception:
            return False

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

    def _existing_token(self) -> str:
        try:
            import keyring
            return keyring.get_password("ImobHunter-BR", "sinter_cib_api_token") or ""
        except Exception:
            return ""

    def _save(self) -> None:
        problems = []
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
                setattr(source, "data_path", Path(value).expanduser() if value else None)

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
        self.settings.sync()
        if token and not token_saved:
            QMessageBox.warning(
                self, "Token não persistido",
                "As demais configurações foram salvas, mas o cofre de credenciais do sistema "
                "não está disponível. O token permanece apenas nesta sessão."
            )
        QMessageBox.information(self, "Configurações salvas", "As configurações foram aplicadas à pesquisa nesta sessão.")
        self.accept()
