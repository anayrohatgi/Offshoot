"""SQLite state. Only the Coordinator (and the read-only review tools) touch it.

One row per paper, keyed by arxiv_id, holding the full extraction record for
accepts and rejects alike. One row per run, so "did last night's run finish?"
is a query rather than a guess.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    arxiv_id      TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    published     TEXT,
    status        TEXT NOT NULL,          -- 'extracted' | 'failed'
    attempts      INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    verdict       TEXT,                   -- 'pass' | 'reject'
    record_json   TEXT,
    doc_id        TEXT,
    doc_url       TEXT,
    dispatched_at TEXT,
    first_seen_at TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    fetched     INTEGER,
    attempted   INTEGER,
    passed      INTEGER,
    rejected    INTEGER,
    failed      INTEGER,
    dispatched  INTEGER
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def is_done(conn: sqlite3.Connection, arxiv_id: str, max_attempts: int) -> bool:
    """True if the paper must not be extracted again.

    Extracted papers are never redone. Failed papers are retried on later
    runs until max_attempts, so a transient arXiv or API error self-heals.
    """
    row = conn.execute(
        "SELECT status, attempts FROM papers WHERE arxiv_id = ?", (arxiv_id,)
    ).fetchone()
    if row is None:
        return False
    return row["status"] == "extracted" or row["attempts"] >= max_attempts


def save_extraction(conn: sqlite3.Connection, record: dict) -> None:
    paper = record["paper"]
    now = _now()
    conn.execute(
        """
        INSERT INTO papers (arxiv_id, title, published, status, attempts,
                            verdict, record_json, first_seen_at, updated_at)
        VALUES (?, ?, ?, 'extracted', 1, ?, ?, ?, ?)
        ON CONFLICT(arxiv_id) DO UPDATE SET
            status = 'extracted', attempts = attempts + 1, error = NULL,
            verdict = excluded.verdict, record_json = excluded.record_json,
            updated_at = excluded.updated_at
        """,
        (paper["arxiv_id"], paper["title"], paper.get("published"),
         record["verdict"], json.dumps(record), now, now),
    )
    conn.commit()


def save_failure(conn: sqlite3.Connection, paper: dict, error: str) -> None:
    now = _now()
    conn.execute(
        """
        INSERT INTO papers (arxiv_id, title, published, status, attempts,
                            error, first_seen_at, updated_at)
        VALUES (?, ?, ?, 'failed', 1, ?, ?, ?)
        ON CONFLICT(arxiv_id) DO UPDATE SET
            attempts = attempts + 1, error = excluded.error,
            updated_at = excluded.updated_at
        """,
        (paper["arxiv_id"], paper["title"], paper.get("published"), error, now, now),
    )
    conn.commit()


def pending_dispatch(conn: sqlite3.Connection) -> list[dict]:
    """Accepted records with no Doc yet, including ones a previous run failed to send."""
    rows = conn.execute(
        "SELECT record_json FROM papers "
        "WHERE verdict = 'pass' AND doc_id IS NULL ORDER BY first_seen_at"
    ).fetchall()
    return [json.loads(r["record_json"]) for r in rows]


def mark_dispatched(conn: sqlite3.Connection, arxiv_id: str, doc_id: str, doc_url: str) -> None:
    now = _now()
    conn.execute(
        "UPDATE papers SET doc_id = ?, doc_url = ?, dispatched_at = ?, updated_at = ? "
        "WHERE arxiv_id = ?",
        (doc_id, doc_url, now, now, arxiv_id),
    )
    conn.commit()


def start_run(conn: sqlite3.Connection) -> int:
    cur = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (_now(),))
    conn.commit()
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, **counts: int) -> None:
    """A run with finished_at NULL crashed part-way."""
    columns = ("fetched", "attempted", "passed", "rejected", "failed", "dispatched")
    conn.execute(
        f"UPDATE runs SET finished_at = ?, {', '.join(c + ' = ?' for c in columns)} WHERE id = ?",
        (_now(), *(counts.get(c, 0) for c in columns), run_id),
    )
    conn.commit()
