def main() -> None:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise RuntimeError(
            "A interface desktop requer a instalação do extra 'desktop': "
            "pip install -e '.[desktop]'"
        ) from exc

    from .application.search import SearchService
    from .infrastructure.local_db import LocalDatabase
    from .sources.registry import build_default_registry
    from .ui import apply_style, build_window, coverage_from_project_root

    app = QApplication([])
    apply_style(app)

    registry = build_default_registry()
    database = LocalDatabase.default()
    service = SearchService(registry, database)
    coverage = coverage_from_project_root()

    window = build_window(service, coverage)
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
