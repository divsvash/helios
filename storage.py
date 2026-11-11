"""Local persistence for sessions. One table, deliberately -- no
schema designed around comparison yet, since comparison's actual
shape is still an open question.
"""

import json
import sqlite3
from pathlib import Path


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            repo_path TEXT NOT NULL,
            task TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            ended_at TEXT,
            check_cmds_json TEXT NOT NULL,
            checks_before_json TEXT NOT NULL,
            baseline_json TEXT NOT NULL,
            evidence_json TEXT
        )
        """
    )
    conn.commit()
    return conn


def open_session(
    conn, session_id, repo_path, task, created_at, check_cmds, checks_before, baseline_snapshot
):
    conn.execute(
        "INSERT INTO sessions (id, repo_path, task, status, created_at, "
        "ended_at, check_cmds_json, checks_before_json, baseline_json, evidence_json) "
        "VALUES (?, ?, ?, 'open', ?, NULL, ?, ?, ?, NULL)",
        (
            session_id,
            repo_path,
            task,
            created_at,
            json.dumps(check_cmds),
            json.dumps(checks_before),
            json.dumps(baseline_snapshot.to_dict()),
        ),
    )
    conn.commit()


def close_session(conn, session_id, ended_at, evidence: dict):
    conn.execute(
        "UPDATE sessions SET status = 'closed', ended_at = ?, evidence_json = ? WHERE id = ?",
        (ended_at, json.dumps(evidence), session_id),
    )
    conn.commit()


def get_open_session(conn, session_id: str | None, repo_path: str | None) -> dict | None:
    """Fetch a specific open session by id, or the most recent open
    session (optionally scoped to a repo) if no id is given.
    """
    cols = "id, repo_path, task, check_cmds_json, checks_before_json"
    if session_id:
        row = conn.execute(
            f"SELECT {cols} FROM sessions WHERE id = ? AND status = 'open'",
            (session_id,),
        ).fetchone()
    else:
        if repo_path:
            row = conn.execute(
                f"SELECT {cols} FROM sessions "
                "WHERE status = 'open' AND repo_path = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (repo_path,),
            ).fetchone()
        else:
            row = conn.execute(
                f"SELECT {cols} FROM sessions "
                "WHERE status = 'open' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
    if not row:
        return None
    return {
        "session_id": row[0],
        "repo_path": row[1],
        "task": row[2],
        "check_cmds": json.loads(row[3]),
        "checks_before": json.loads(row[4]),
    }


def list_sessions(conn) -> list:
    rows = conn.execute(
        "SELECT id, status, created_at, task, repo_path FROM sessions ORDER BY created_at DESC"
    ).fetchall()
    return [
        {
            "session_id": r[0],
            "status": r[1],
            "created_at": r[2],
            "task": r[3],
            "repo_path": r[4],
        }
        for r in rows
    ]


def get_evidence(conn, session_id: str) -> dict | None:
    row = conn.execute(
        "SELECT evidence_json FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row or not row[0]:
        return None
    return json.loads(row[0])
