import sqlite3
from datetime import UTC, datetime
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
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS searches ("
                "id INTEGER PRIMARY KEY, query TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            conn.commit()

    def record_search(self, query: str) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT INTO searches(query, created_at) VALUES (?, ?)",
                (query, datetime.now(UTC).isoformat()),
            )
            conn.commit()

    def search_count(self) -> int:
        with sqlite3.connect(self.path) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM searches").fetchone()[0])
