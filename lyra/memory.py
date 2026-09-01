"""
Phase 3 — personal memory (SQLite).
------------------------------------
Two tables, per the plan's Phase 3 split (Person B's parallel track):
    users         -- one row: the person using this desktop app, their name
                     + free-form preferences text.
    chat_history  -- every turn (user + assistant), tagged with a
                     session_id generated once per app run.

This module has zero PySide6 import and zero provider-SDK import, same
"headless" rule as llm_client.py / stt.py / tts.py -- it's plain sqlite3
(stdlib), reusable from a CLI or a GUI without changes.

llm_client.py is the only caller: it extracts a name from what the user
just typed/said, persists it, logs both sides of the turn, and prepends
whatever's known about the user to the prompt sent to the LLM as a short
system-style preamble. Providers never see this module or know it exists
-- same "provider is just prompt in, text out" contract as before, so
adding memory didn't require touching providers/, worker.py, or main.py.
"""

import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent.parent / "lyra_memory.db"

# One id per process run. The Phase 3 checkpoint only requires remembering
# a name *within* a session -- but persisting it in `users` also makes it
# survive a restart, which is a strict superset of that requirement and
# costs nothing extra.
SESSION_ID = uuid.uuid4().hex

# Conservative on purpose: two explicit, low-false-positive patterns rather
# than trying to catch every phrasing ("I'm fine" must never be read as a
# name). Good enough for the Phase 3 checkpoint; Phase 5's "personal memory
# refinement" is where this is meant to get more robust.
_NAME_PATTERNS = [
    re.compile(r"\bmy name is\s+([A-Za-z][A-Za-z\-']{1,30})\b", re.IGNORECASE),
    re.compile(r"\bcall me\s+([A-Za-z][A-Za-z\-']{1,30})\b", re.IGNORECASE),
]


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    """Create tables if they don't exist yet. Safe to call every startup."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY CHECK (id = 1),  -- single-user app, one row
                name TEXT,
                preferences TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,       -- "user" or "assistant"
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )


def get_user_name() -> Optional[str]:
    with _connect() as conn:
        row = conn.execute("SELECT name FROM users WHERE id = 1").fetchone()
    return row[0] if row and row[0] else None


def set_user_name(name: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO users (id, name, updated_at) VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET name = excluded.name, updated_at = excluded.updated_at
            """,
            (name, now),
        )


def maybe_extract_name(user_text: str) -> Optional[str]:
    """Look for an explicit self-introduction in `user_text`; return the name if found."""
    for pattern in _NAME_PATTERNS:
        match = pattern.search(user_text)
        if match:
            return match.group(1).strip().capitalize()
    return None


def log_message(role: str, content: str) -> None:
    if not content or not content.strip():
        return
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO chat_history (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (SESSION_ID, role, content, now),
        )


def build_memory_prefix() -> str:
    """
    A short preamble to prepend to the prompt sent to the LLM, or "" if
    nothing is known yet about the user. Framed explicitly as background
    context (not something the user just said) so the model doesn't treat
    it as part of the live turn.
    """
    name = get_user_name()
    if not name:
        return ""
    return (
        f"[Background: the user's name is {name}. Address them by name "
        "when it feels natural, but don't force it into every reply. "
        "This line is context, not something the user just said.]\n\n"
    )


init_db()
