import sqlite3
from pathlib import Path

class LocalDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def default(cls) -> "LocalDatabase":
        return cls(Path.home() / ".imobhunter" / "imobhunter.db")

    def _initialize(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS searches (id INTEGER PRIMARY KEY, query TEXT NOT NULL, created_at TEXT NOT NULL)")
            conn.commit()
