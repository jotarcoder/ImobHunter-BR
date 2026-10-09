def main() -> None:
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox, QLineEdit
    except ImportError as exc:
        raise RuntimeError(
            "A interface desktop requer a instalação do extra 'desktop': "
            "pip install -e '.[desktop]'"
        ) from exc

    from .licensing import CONTACT_PHONE, LicenseError, activate, get_user_id
    from .application.search import SearchService
    from .infrastructure.local_db import LocalDatabase
    from .sources.registry import build_default_registry
    from .ui import apply_style, build_window, coverage_from_project_root

    app = QApplication([])
    apply_style(app)
    user_id = get_user_id()
    QMessageBox.information(
        None,
        "Ativação do ImobHunter",
        "A instalação está liberada, mas o uso dos recursos exige uma licença ativa.\n\n"
        f"Seu ID de usuário é:\n{user_id}\n\n"
        f"Para obter a ativação, entre em contato: {CONTACT_PHONE}",
    )
    key, accepted = QInputDialog.getText(
        None, "Ativar licença", "Cole a chave hexadecimal de ativação:",
        QLineEdit.EchoMode.Password,
    )
    if not accepted or not key.strip():
        QMessageBox.information(None, "Licença necessária", f"Entre em contato com {CONTACT_PHONE} para obter sua chave.")
        return
    activation_key = key.strip()
    try:
        activate(user_id, activation_key)
    except LicenseError as exc:
        QMessageBox.critical(None, "Ativação recusada", f"{exc}\n\nContato: {CONTACT_PHONE}")
        return

    registry = build_default_registry()
    database = LocalDatabase.default()
    service = SearchService(registry, database)
    coverage = coverage_from_project_root()
    window = build_window(service, coverage)

    # Recheck while the application is open so suspensions and expirations take effect.
    def revalidate_license() -> None:
        try:
            activate(user_id, activation_key)
        except LicenseError:
            QMessageBox.critical(
                window,
                "Licença suspensa",
                "O servidor não autorizou a continuidade do uso. "
                f"Entre em contato com {CONTACT_PHONE}.",
            )
            window.close()
            app.quit()

    license_timer = QTimer(window)
    license_timer.setInterval(5 * 60 * 1000)
    license_timer.timeout.connect(revalidate_license)
    license_timer.start()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
