"""SQLite storage for jobs, scores, applications and source runs."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from jobhunter.config import DB_PATH
from jobhunter.models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    url_key TEXT NOT NULL UNIQUE,
    content_key TEXT NOT NULL UNIQUE,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    remote INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    posted_at TEXT,
    apply_url TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    also_on TEXT NOT NULL DEFAULT '',
    relevant INTEGER,
    role TEXT,
    markets TEXT NOT NULL DEFAULT '',
    eligibility TEXT,
    filter_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_relevant ON jobs(relevant, eligibility);

CREATE TABLE IF NOT EXISTS scores (
    job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
    score INTEGER NOT NULL,
    resume TEXT,
    reason TEXT,
    gaps TEXT,
    scored_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS applications (
    job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
    status TEXT NOT NULL,
    resume_path TEXT,
    applied_at TEXT,
    follow_up_on TEXT,
    notes TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_runs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    fetched INTEGER NOT NULL DEFAULT 0,
    added INTEGER NOT NULL DEFAULT 0,
    message TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # Databases made before apply_url existed need the column before the schema runs.
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'jobs'").fetchone():
        if "apply_url" not in {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}:
            conn.execute("ALTER TABLE jobs ADD COLUMN apply_url TEXT NOT NULL DEFAULT ''")
    conn.executescript(SCHEMA)
    return conn


def upsert_job(conn: sqlite3.Connection, job: Job) -> bool:
    """Store a job, or update the existing copy. Returns True if it is new."""
    seen = now()
    row = conn.execute(
        "SELECT id, source, also_on FROM jobs WHERE url_key = ? OR content_key = ?",
        (job.url_key, job.content_key),
    ).fetchone()
    if row:
        also_on = {s for s in row["also_on"].split(",") if s}
        if job.source != row["source"]:
            also_on.add(job.source)
        conn.execute(
            "UPDATE jobs SET last_seen = ?, also_on = ?, apply_url = CASE WHEN ? != '' THEN ? ELSE apply_url END WHERE id = ?",
            (seen, ",".join(sorted(also_on)), job.apply_url, job.apply_url, row["id"]),
        )
        return False
    conn.execute(
        """INSERT INTO jobs (source, url, url_key, content_key, company, title, location,
                             remote, description, posted_at, apply_url, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (job.source, job.url, job.url_key, job.content_key, job.company, job.title,
         job.location, int(job.remote), job.description, job.posted_at, job.apply_url, seen, seen),
    )
    return True


def set_application(conn, job_id: int, status: str, resume_path: str | None = None, notes: str | None = None,
                    applied_at: str | None = None, follow_up_on: str | None = None) -> None:
    """Record an application's status, keeping any earlier values not given here."""
    conn.execute(
        """INSERT INTO applications (job_id, status, resume_path, applied_at, follow_up_on, notes, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(job_id) DO UPDATE SET status = excluded.status,
               resume_path = COALESCE(excluded.resume_path, resume_path),
               applied_at = COALESCE(excluded.applied_at, applied_at),
               follow_up_on = COALESCE(excluded.follow_up_on, follow_up_on),
               notes = COALESCE(excluded.notes, notes),
               updated_at = excluded.updated_at""",
        (job_id, status, resume_path, applied_at, follow_up_on, notes, now()),
    )


def record_run(conn, source: str, ok: bool, fetched: int = 0, added: int = 0, message: str = "") -> None:
    conn.execute(
        "INSERT INTO source_runs (source, started_at, ok, fetched, added, message) VALUES (?, ?, ?, ?, ?, ?)",
        (source, now(), int(ok), fetched, added, message),
    )


def last_success(conn, source: str) -> datetime | None:
    row = conn.execute(
        "SELECT MAX(started_at) AS t FROM source_runs WHERE source = ? AND ok = 1", (source,)
    ).fetchone()
    return datetime.fromisoformat(row["t"]) if row and row["t"] else None
