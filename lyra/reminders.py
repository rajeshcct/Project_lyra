"""
Phase 5 — reminders storage (SQLite).
--------------------------------------
Same pattern as memory.py: plain sqlite3 (stdlib), zero PySide6 import,
zero provider-SDK import, reusable from a CLI or the GUI without changes.
Lives in the same lyra_memory.db file as the users/chat_history tables
(one db file for the whole app, per the existing DB_PATH convention) but
gets its own module rather than being folded into memory.py, since
reminders are a distinct concern from personal-memory/context.

Scope note: this is a *list*, not an alarm clock. Lyra is a desktop app
that isn't always running, so there is no background scheduler here and
no OS notification when a reminder's time arrives — `remind_at` is stored
as whatever free-text the user said ("tomorrow at 5pm", "next Friday")
and surfaced back to them when they ask what's on their list, via the
`list_reminders` tool. Actual time-triggered alerts would need an
always-running process or OS-level scheduled task, which is out of scope
for a chat tool call and is left as a later phase if it's ever wanted.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent.parent / "lyra_memory.db"


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    """Create the reminders table if it doesn't exist yet. Safe to call
    every startup — same convention as memory.init_db()."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                remind_at TEXT,           -- free-text, not parsed (see module docstring)
                done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )


def add_reminder(text: str, remind_at: Optional[str] = None) -> int:
    """Store a reminder and return its id."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO reminders (text, remind_at, created_at) VALUES (?, ?, ?)",
            (text, remind_at, now),
        )
        return cursor.lastrowid


def list_reminders(include_done: bool = False) -> list[dict]:
    """All reminders, most recently created first."""
    query = "SELECT id, text, remind_at, done, created_at FROM reminders"
    if not include_done:
        query += " WHERE done = 0"
    query += " ORDER BY id DESC"
    with _connect() as conn:
        rows = conn.execute(query).fetchall()
    return [
        {
            "id": row[0],
            "text": row[1],
            "remind_at": row[2],
            "done": bool(row[3]),
            "created_at": row[4],
        }
        for row in rows
    ]


def complete_reminder(reminder_id: int) -> bool:
    """Mark a reminder done. Returns True if a row was actually updated."""
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE reminders SET done = 1 WHERE id = ?", (reminder_id,)
        )
        return cursor.rowcount > 0


init_db()
