from __future__ import annotations

from urllib.parse import quote
from threading import Thread


def main() -> None:
    try:
        from PySide6.QtCore import QObject, QTimer, QUrl, Signal
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import (
            QApplication,
            QDialog,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMessageBox,
            QPushButton,
            QVBoxLayout,
        )
    except ImportError as exc:
        raise RuntimeError(
            "A interface desktop requer a instalação do extra 'desktop': "
            "pip install -e '.[desktop]'"
        ) from exc

    from .licensing import LicenseError, get_user_id, saved_activation_key, save_activation_key
    from .offline_license import cached_authorization, check_license
    from .application.search import SearchService
    from .infrastructure.local_db import LocalDatabase
    from .sources.registry import build_default_registry
    from .ui import apply_style, build_window, coverage_from_project_root
    from .ui_settings import apply_saved_source_settings

    app = QApplication([])
    apply_style(app)
    user_id = get_user_id()

    cached_key = saved_activation_key()
    startup_problem = ""
    if cached_key:
        try:
            # A valid signed certificate makes startup immediate, even offline.
            cached_authorization(user_id, cached_key)
        except LicenseError:
            try:
                # Existing clients can migrate by obtaining their first signed certificate.
                check_license(user_id, cached_key)
            except LicenseError as exc:
                startup_problem = str(exc)
                # Never delete a paid key for a timeout, edge error or denial.
                cached_key = None

    class ActivationDialog(QDialog):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Ativar ImobHunter-BR")
            self.setMinimumWidth(520)
            self.activation_key = ""
            layout = QVBoxLayout(self)
            layout.setSpacing(12)

            title = QLabel("Ativação do ImobHunter-BR")
            title.setStyleSheet("font-size: 22px; font-weight: 800;")
            layout.addWidget(title)
            intro = QLabel(
                "Para liberar as pesquisas e os dossiês, informe a chave de licença "
                "emitida pela equipe ImobHunter. Sua licença será validada online."
            )
            intro.setWordWrap(True)
            layout.addWidget(intro)

            layout.addWidget(QLabel("Seu ID exclusivo de usuário"))
            id_row = QHBoxLayout()
            self.id_field = QLineEdit(user_id)
            self.id_field.setReadOnly(True)
            id_row.addWidget(self.id_field, 1)
            copy_button = QPushButton("Copiar ID")
            copy_button.clicked.connect(lambda: app.clipboard().setText(user_id))
            id_row.addWidget(copy_button)
            layout.addLayout(id_row)

            layout.addWidget(QLabel("Chave de ativação"))
            self.key_field = QLineEdit()
            self.key_field.setPlaceholderText("Cole aqui sua chave de 64 caracteres")
            self.key_field.setEchoMode(QLineEdit.EchoMode.Password)
            # Prefill the saved key even when the previous verification failed.
            stored_key = saved_activation_key()
            if stored_key:
                self.key_field.setText(stored_key)
            self.key_field.returnPressed.connect(self.try_activate)
            layout.addWidget(self.key_field)

            self.status = QLabel(startup_problem)
            self.status.setWordWrap(True)
            layout.addWidget(self.status)

            buttons = QHBoxLayout()
            whatsapp = QPushButton("Solicitar pelo WhatsApp")
            whatsapp.clicked.connect(self.open_whatsapp)
            buttons.addWidget(whatsapp)
            buttons.addStretch(1)
            activate_button = QPushButton("Validar e ativar")
            activate_button.setDefault(True)
            activate_button.clicked.connect(self.try_activate)
            buttons.addWidget(activate_button)
            layout.addLayout(buttons)

            self.key_field.setFocus()

        def open_whatsapp(self) -> None:
            message = (
                "Olá! Quero adquirir o serviço ImobHunter-BR e preciso de ajuda "
                f"com a ativação. Meu ID de usuário é {user_id}. "
                "Gostaria de receber informações sobre os planos mensal e anual."
            )
            url = "https://wa.me/5511999037737?text=" + quote(message)
            opened = QDesktopServices.openUrl(QUrl(url))
            if not opened:
                QMessageBox.warning(
                    self,
                    "WhatsApp",
                    "Não foi possível abrir o WhatsApp automaticamente. "
                    "Verifique seu navegador padrão ou acesse https://wa.me/5511999037737.",
                )

        def try_activate(self) -> None:
            key = self.key_field.text().strip()
            if not key:
                self.status.setText("Cole a chave de ativação para continuar.")
                return
            self.status.setText("Validando licença com o servidor…")
            QApplication.processEvents()
            try:
                check_license(user_id, key)
            except LicenseError as exc:
                self.status.setText(str(exc))
                return
            try:
                save_activation_key(key)
            except OSError as exc:
                self.status.setText(f"Licença ativada, mas não foi possível salvar localmente: {exc}")
                return
            self.activation_key = key
            self.accept()

    activation_key = cached_key or ""
    if not activation_key:
        dialog = ActivationDialog()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        activation_key = dialog.activation_key

    registry = build_default_registry()
    apply_saved_source_settings(registry)
    database = LocalDatabase.default()
    service = SearchService(registry, database)
    coverage = coverage_from_project_root()
    window = build_window(service, coverage)

    # Network checks must not freeze the UI (8-second timeout), nor purge keys.
    class ValidationSignals(QObject):
        complete = Signal(str)

    signals = ValidationSignals(window)
    check_running = False

    def validation_finished(error: str) -> None:
        nonlocal check_running
        check_running = False
        if error:
            QMessageBox.warning(
                window,
                "Validação de licença",
                error + "\n\nSua chave foi preservada. Conecte-se para renovar a validação.",
            )
            window.close()
            app.quit()

    def revalidate_license() -> None:
        nonlocal check_running
        if check_running:
            return
        check_running = True

        def work() -> None:
            try:
                check_license(user_id, activation_key)
                error = ""
            except LicenseError as exc:
                error = str(exc)
            signals.complete.emit(error)

        Thread(target=work, daemon=True).start()

    signals.complete.connect(validation_finished)
    license_timer = QTimer(window)
    license_timer.setInterval(5 * 60 * 1000)
    license_timer.timeout.connect(revalidate_license)
    license_timer.start()
    window.show()
    QTimer.singleShot(0, revalidate_license)
    app.exec()


if __name__ == "__main__":
    main()
