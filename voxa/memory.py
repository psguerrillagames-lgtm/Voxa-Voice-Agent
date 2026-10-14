"""Long-term incident memory.

Short-term memory is the live incident session (conversation + findings).
Long-term memory is this store: every resolved incident is saved with its root
cause, the action taken, whether it worked, and a one-line lesson. When a new
alert fires, similar past incidents are recalled and handed to the planner.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from voxa.rag import BM25, tokenize

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    alert TEXT NOT NULL,
    root_service TEXT NOT NULL,
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL,
    lesson TEXT NOT NULL
)
"""


@dataclass
class IncidentRecord:
    alert: dict
    root_service: str
    category: str
    summary: str
    action: str
    outcome: str
    lesson: str


class IncidentMemory:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute(SCHEMA)

    def remember(self, rec: IncidentRecord) -> int:
        row = asdict(rec)
        row["alert"] = json.dumps(rec.alert)
        cur = self.db.execute(
            "INSERT INTO incidents (at, alert, root_service, category, summary, action, "
            "outcome, lesson) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (time.time(), row["alert"], rec.root_service, rec.category, rec.summary,
             rec.action, rec.outcome, rec.lesson))
        self.db.commit()
        return cur.lastrowid

    def all(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM incidents ORDER BY at DESC").fetchall()
        return [dict(r) | {"alert": json.loads(r["alert"])} for r in rows]

    def recall(self, query: str, k: int = 3) -> list[dict]:
        rows = self.all()
        if not rows:
            return []
        docs = [tokenize(f"{r['alert']} {r['root_service']} {r['category']} {r['summary']} "
                         f"{r['lesson']}") for r in rows]
        scores = BM25(docs).scores(tokenize(query))
        ranked = sorted(zip(scores, rows, strict=True), key=lambda p: p[0], reverse=True)
        return [r for s, r in ranked[:k] if s > 0]

    def context(self, query: str, k: int = 3) -> str:
        return "\n".join(
            f"- {r['root_service']} {r['category']}: {r['summary']} -> {r['action']} "
            f"({r['outcome']}). Lesson: {r['lesson']}" for r in self.recall(query, k))
