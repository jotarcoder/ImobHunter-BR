from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget
from .application.search import SearchService
from .infrastructure.local_db import LocalDatabase
from .sources.registry import build_default_registry

def main() -> None:
    app = QApplication([])
    registry = build_default_registry()
    database = LocalDatabase.default()
    SearchService(registry, database)
    window = QMainWindow()
    window.setWindowTitle("ImobHunter-BR")
    window.resize(1180, 760)
    root = QWidget()
    layout = QVBoxLayout(root)
    title = QLabel("ImobHunter-BR")
    title.setStyleSheet("font-size: 28px; font-weight: 700;")
    layout.addWidget(title)
    layout.addWidget(QLabel("Inteligência imobiliária local-first"))
    layout.addStretch()
    window.setCentralWidget(root)
    window.show()
    app.exec()
