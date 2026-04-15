"""
Application Tracker
===================
SQLite-backed store for all job applications.  Each row represents one job
that has been discovered, shortlisted, drafted, submitted, or responded to.

Status pipeline:
    discovered → shortlisted → drafted → submitted → response_received
                                                   → interview_scheduled
                                                   → offer_received
                                                   → rejected
                                                   → withdrawn
"""

from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path
from typing import Optional

_DB_PATH = Path(".job_agent_data") / "jobs.db"

STATUSES = [
    "discovered",
    "shortlisted",
    "drafted",
    "submitted",
    "response_received",
    "interview_scheduled",
    "offer_received",
    "rejected",
    "withdrawn",
]


class JobTracker:
    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._db = str(db_path)
        db_path.parent.mkdir(exist_ok=True)
        self._init_db()

    # ── schema ────────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS applications (
                    id            TEXT PRIMARY KEY,
                    title         TEXT NOT NULL,
                    company       TEXT,
                    location      TEXT,
                    remote        INTEGER DEFAULT 0,
                    url           TEXT,
                    description   TEXT,
                    source        TEXT,
                    posted_at     TEXT,
                    salary_min    INTEGER,
                    salary_max    INTEGER,
                    tags          TEXT,          -- JSON array
                    status        TEXT DEFAULT 'discovered',
                    relevance_score    INTEGER,
                    relevance_label    TEXT,
                    relevance_reason   TEXT,
                    cover_letter  TEXT,
                    notes         TEXT,
                    applied_at    TEXT,
                    updated_at    TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS follow_ups (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id      TEXT NOT NULL,
                    due_date    TEXT NOT NULL,
                    message     TEXT,
                    done        INTEGER DEFAULT 0
                )
            """)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db)
        conn.row_factory = sqlite3.Row
        return conn

    # ── write operations ──────────────────────────────────────────────────────

    def upsert_job(self, job: dict) -> None:
        """Insert or update a job (by id). Does NOT overwrite status/notes if already exists."""
        now = _now()
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id, status, notes, cover_letter, applied_at FROM applications WHERE id = ?",
                (job["id"],),
            ).fetchone()

            if existing:
                # Refresh discovery data but preserve user-managed fields
                conn.execute("""
                    UPDATE applications SET
                        title=?, company=?, location=?, remote=?, url=?,
                        description=?, source=?, posted_at=?, salary_min=?, salary_max=?,
                        tags=?, relevance_score=?, relevance_label=?, relevance_reason=?,
                        updated_at=?
                    WHERE id=?
                """, (
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("location", ""),
                    int(bool(job.get("remote", False))),
                    job.get("url", ""),
                    job.get("description", ""),
                    job.get("source", ""),
                    job.get("posted_at", ""),
                    job.get("salary_min"),
                    job.get("salary_max"),
                    json.dumps(job.get("tags", [])),
                    _relevance(job, "score"),
                    _relevance(job, "label"),
                    _relevance(job, "reasoning"),
                    now,
                    job["id"],
                ))
            else:
                conn.execute("""
                    INSERT INTO applications (
                        id, title, company, location, remote, url, description,
                        source, posted_at, salary_min, salary_max, tags,
                        status, relevance_score, relevance_label, relevance_reason,
                        updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    job["id"],
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("location", ""),
                    int(bool(job.get("remote", False))),
                    job.get("url", ""),
                    job.get("description", ""),
                    job.get("source", ""),
                    job.get("posted_at", ""),
                    job.get("salary_min"),
                    job.get("salary_max"),
                    json.dumps(job.get("tags", [])),
                    "discovered",
                    _relevance(job, "score"),
                    _relevance(job, "label"),
                    _relevance(job, "reasoning"),
                    now,
                ))

    def update_status(self, job_id: str, status: str, notes: str = "") -> None:
        now = _now()
        applied_at = now if status == "submitted" else None
        with self._conn() as conn:
            if applied_at:
                conn.execute(
                    "UPDATE applications SET status=?, notes=?, applied_at=?, updated_at=? WHERE id=?",
                    (status, notes, applied_at, now, job_id),
                )
            else:
                conn.execute(
                    "UPDATE applications SET status=?, notes=?, updated_at=? WHERE id=?",
                    (status, notes, now, job_id),
                )

    def save_cover_letter(self, job_id: str, cover_letter: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE applications SET cover_letter=?, updated_at=? WHERE id=?",
                (cover_letter, _now(), job_id),
            )

    def add_follow_up(self, job_id: str, due_date: str, message: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO follow_ups (job_id, due_date, message) VALUES (?,?,?)",
                (job_id, due_date, message),
            )

    def mark_follow_up_done(self, follow_up_id: int) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE follow_ups SET done=1 WHERE id=?", (follow_up_id,))

    # ── read operations ───────────────────────────────────────────────────────

    def get_jobs(self, status: Optional[str] = None) -> list[dict]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM applications WHERE status=? ORDER BY relevance_score DESC NULLS LAST, updated_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM applications ORDER BY relevance_score DESC NULLS LAST, updated_at DESC"
                ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_job(self, job_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM applications WHERE id=?", (job_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None

    def get_stats(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM applications GROUP BY status"
            ).fetchall()
        stats = {s: 0 for s in STATUSES}
        for row in rows:
            stats[row["status"]] = row["cnt"]
        stats["total"] = sum(stats.values())
        return stats

    def get_pending_follow_ups(self) -> list[dict]:
        today = datetime.date.today().isoformat()
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT f.id, f.job_id, f.due_date, f.message,
                       a.title, a.company
                FROM follow_ups f
                JOIN applications a ON f.job_id = a.id
                WHERE f.done = 0 AND f.due_date <= ?
                ORDER BY f.due_date
            """, (today,)).fetchall()
        return [dict(r) for r in rows]


# ── helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _relevance(job: dict, key: str):
    rel = job.get("relevance")
    if isinstance(rel, dict):
        return rel.get(key)
    return None


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    # Deserialise JSON-stored tags
    try:
        d["tags"] = json.loads(d.get("tags") or "[]")
    except Exception:
        d["tags"] = []
    d["remote"] = bool(d.get("remote", 0))
    return d
