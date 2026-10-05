"""SQLite storage. One connection guarded by a lock; every query here is small."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    ts          REAL NOT NULL,
    engine      TEXT,              -- NULL for system-level messages
    kind        TEXT NOT NULL,     -- captcha | rate_limited | blocked | challenge | timeout | parse_error | ...
    detail      TEXT,
    host        TEXT,              -- upstream host only; query strings are never stored
    suspended_s INTEGER,
    level       TEXT
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS events_engine_ts ON events(engine, ts);

-- Per-scrape deltas of SearXNG's /metrics counters (only rows with traffic).
CREATE TABLE IF NOT EXISTS traffic (
    ts       REAL NOT NULL,
    engine   TEXT NOT NULL,
    sent     INTEGER NOT NULL,
    results  INTEGER NOT NULL,
    total_s  REAL,
    http_s   REAL
);
CREATE INDEX IF NOT EXISTS traffic_ts ON traffic(ts);
CREATE INDEX IF NOT EXISTS traffic_engine_ts ON traffic(engine, ts);

CREATE TABLE IF NOT EXISTS probes (
    id            INTEGER PRIMARY KEY,
    ts            REAL NOT NULL,
    kind          TEXT NOT NULL,   -- canary | manual
    query         TEXT,
    target        TEXT,            -- engine name for manual engine tests
    duration_ms   INTEGER,
    ok            INTEGER NOT NULL,
    total_results INTEGER,
    error         TEXT
);
CREATE INDEX IF NOT EXISTS probes_ts ON probes(ts);

CREATE TABLE IF NOT EXISTS probe_results (
    probe_id INTEGER NOT NULL REFERENCES probes(id) ON DELETE CASCADE,
    engine   TEXT NOT NULL,
    status   TEXT NOT NULL,        -- ok | error | empty
    results  INTEGER,
    detail   TEXT
);
CREATE INDEX IF NOT EXISTS probe_results_probe ON probe_results(probe_id);
CREATE INDEX IF NOT EXISTS probe_results_engine ON probe_results(engine);

CREATE TABLE IF NOT EXISTS alerts (
    id        INTEGER PRIMARY KEY,
    key       TEXT NOT NULL,
    severity  TEXT NOT NULL,       -- critical | warning | info
    title     TEXT NOT NULL,
    detail    TEXT,
    opened    REAL NOT NULL,
    resolved  REAL,
    notified  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS alerts_key ON alerts(key, resolved);

CREATE TABLE IF NOT EXISTS lifecycle (
    ts     REAL NOT NULL,
    kind   TEXT NOT NULL,          -- start | apply | rollback | update | restore
    detail TEXT
);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        """Run a statement; returns lastrowid."""
        with self._lock:
            return self._conn.execute(sql, params).lastrowid or 0

    def executemany(self, sql: str, rows: list[tuple]) -> None:
        if not rows:
            return
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.executemany(sql, rows)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM kv WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else default

    def kv_set(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    def lifecycle(self, kind: str, detail: str = "") -> None:
        self.execute("INSERT INTO lifecycle(ts, kind, detail) VALUES(?, ?, ?)", (time.time(), kind, detail))

    def prune(self, retention_days: int) -> None:
        cutoff = time.time() - retention_days * 86400
        with self._lock:
            self._conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
            self._conn.execute("DELETE FROM traffic WHERE ts < ?", (cutoff,))
            self._conn.execute("DELETE FROM probes WHERE ts < ?", (cutoff,))
            self._conn.execute("DELETE FROM alerts WHERE resolved IS NOT NULL AND resolved < ?", (cutoff,))
            self._conn.execute("DELETE FROM lifecycle WHERE ts < ?", (cutoff - 60 * 86400,))
