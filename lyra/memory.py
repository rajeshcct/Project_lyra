"""
Phase 3 (name-only) + Phase 5 (refinement) — personal memory (SQLite).
------------------------------------------------------------------------
Three tables now:
    users         -- one row: the person using this desktop app, their
                     name, a rolling free-form preferences list, and a
                     rolling conversation summary.
    chat_history  -- every turn (user + assistant), tagged with a
                     session_id generated once per app run, plus a
                     `summarized` flag used by the rolling-summary logic.

This module has zero PySide6 import and zero provider-SDK import, same
"headless" rule as llm_client.py / stt.py / tts.py -- it's plain sqlite3
(stdlib), reusable from a CLI or a GUI without changes. It still doesn't
know how to *call* an LLM (that stays llm_client.py's job) -- but
Phase 5's rolling summary needs an LLM call to condense old turns, so
`maybe_condense_history()` below takes the summarizing call in as a
plain callable rather than importing providers/ itself. Same "provider is
just prompt in, text out" contract as before.

Phase 5 additions over Phase 3:
  - `preferences`: a short, explicit-statement-only extractor
    (maybe_extract_preference), same conservative spirit as the existing
    name extractor -- casual chat should never silently become a stored
    "preference".
  - Rolling-summary context pattern: instead of every prompt only ever
    getting a one-line "the user's name is X" preamble (Phase 3 sent zero
    conversation history to the model at all), build_memory_prefix() now
    also folds in a short rolling summary of older turns plus the last
    few turns verbatim, so the model has continuity across a session
    without the prompt growing unbounded as chat_history grows.
"""

import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "lyra_memory.db"

# One id per process run. The Phase 3 checkpoint only requires remembering
# a name *within* a session -- but persisting it in `users` also makes it
# survive a restart, which is a strict superset of that requirement and
# costs nothing extra.
SESSION_ID = uuid.uuid4().hex

# Conservative on purpose: two explicit, low-false-positive patterns rather
# than trying to catch every phrasing ("I'm fine" must never be read as a
# name).
_NAME_PATTERNS = [
    re.compile(r"\bmy name is\s+([A-Za-z][A-Za-z\-']{1,30})\b", re.IGNORECASE),
    re.compile(r"\bcall me\s+([A-Za-z][A-Za-z\-']{1,30})\b", re.IGNORECASE),
]

# Same conservative spirit as _NAME_PATTERNS: only clear, explicit
# statements of a like/dislike/favorite become a stored preference.
# Deliberately not trying to catch every phrasing of "I enjoy X" — a
# missed preference is a much smaller cost than a wrongly-stored one that
# then colors every future reply.
_PREFERENCE_PATTERNS = [
    (re.compile(r"\bmy favorite (\w[\w \-']{1,40}?) is\s+(.{2,80})", re.IGNORECASE), "favorite {0}: {1}"),
    (re.compile(r"\bi (?:really )?(?:love|like|enjoy|prefer)\s+(.{2,80})", re.IGNORECASE), "likes {0}"),
    (re.compile(r"\bi (?:really )?(?:hate|dislike|can't stand)\s+(.{2,80})", re.IGNORECASE), "dislikes {0}"),
]

# Rolling-summary tuning. Kept small on purpose — this is a hobby desktop
# app talking to free-tier models, not a product with a token budget to
# spare.
RECENT_TURNS_KEPT = 8  # most recent chat_history rows always sent verbatim
SUMMARY_BATCH_SIZE = 10  # how many old rows get folded into the summary at once
MAX_PREFERENCES = 20  # oldest preferences fall off past this so the list stays short


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, coltype: str) -> None:
    """Add `column` to `table` if it isn't there yet. SQLite has no
    'ADD COLUMN IF NOT EXISTS', so check pragma table_info first — this
    keeps init_db() safe to call on both a fresh Phase 5 db and an
    existing Phase 3 db that predates these columns."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db() -> None:
    """Create tables if they don't exist yet, and migrate older dbs
    forward. Safe to call every startup."""
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
        # Phase 5 migrations for dbs created by Phase 3.
        _ensure_column(conn, "users", "summary", "TEXT")
        _ensure_column(conn, "chat_history", "summarized", "INTEGER NOT NULL DEFAULT 0")


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


def maybe_extract_preference(user_text: str) -> Optional[str]:
    """Look for an explicit like/dislike/favorite statement in `user_text`;
    return a short normalized preference string if found, else None."""
    for pattern, template in _PREFERENCE_PATTERNS:
        match = pattern.search(user_text)
        if match:
            groups = [g.strip().rstrip(".!?").strip() for g in match.groups()]
            if any(not g for g in groups):
                continue
            return template.format(*groups)
    return None


def get_preferences() -> list[str]:
    with _connect() as conn:
        row = conn.execute("SELECT preferences FROM users WHERE id = 1").fetchone()
    if not row or not row[0]:
        return []
    return [line for line in row[0].split("\n") if line.strip()]


def add_preference(preference: str) -> None:
    """Append a preference, de-duplicated and capped at MAX_PREFERENCES
    (oldest dropped first) so this can't grow into a huge blob that
    dominates every future prompt."""
    prefs = get_preferences()
    if preference in prefs:
        prefs.remove(preference)
    prefs.append(preference)
    prefs = prefs[-MAX_PREFERENCES:]
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO users (id, preferences, updated_at) VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET preferences = excluded.preferences, updated_at = excluded.updated_at
            """,
            ("\n".join(prefs), now),
        )


def get_summary() -> Optional[str]:
    with _connect() as conn:
        row = conn.execute("SELECT summary FROM users WHERE id = 1").fetchone()
    return row[0] if row and row[0] else None


def set_summary(summary: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO users (id, summary, updated_at) VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET summary = excluded.summary, updated_at = excluded.updated_at
            """,
            (summary, now),
        )


def log_message(role: str, content: str) -> None:
    if not content or not content.strip():
        return
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO chat_history (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (SESSION_ID, role, content, now),
        )


def get_recent_turns(limit: int = RECENT_TURNS_KEPT) -> list[tuple[str, str]]:
    """The most recent `limit` (role, content) rows, oldest first — this is
    what gets sent to the model verbatim on every turn, regardless of
    session, so continuity survives an app restart the same way the name
    already does."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return list(reversed(rows))


def maybe_condense_history(summarize: Callable[[str], str]) -> None:
    """
    Rolling-summary maintenance: if there are more than
    RECENT_TURNS_KEPT + SUMMARY_BATCH_SIZE rows sitting unsummarized,
    fold the oldest SUMMARY_BATCH_SIZE of them (past the recent window
    that stays verbatim) into the running summary via one call to
    `summarize(prompt) -> text`, then mark those rows as summarized so
    they're excluded from future get_recent_turns() calls and never
    re-summarized.

    `summarize` is a plain callable rather than an import of providers/
    so this module stays provider-agnostic — llm_client.py passes in
    whichever provider's .ask is currently configured. If the call fails
    for any reason, the old rows are simply left alone and tried again
    next turn — losing one summarization pass costs nothing but a
    slightly longer history, never data.
    """
    with _connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM chat_history WHERE summarized = 0"
        ).fetchone()[0]
        if total <= RECENT_TURNS_KEPT + SUMMARY_BATCH_SIZE:
            return

        to_fold = conn.execute(
            """
            SELECT id, role, content FROM chat_history
            WHERE summarized = 0
            ORDER BY id ASC
            LIMIT ?
            """,
            (SUMMARY_BATCH_SIZE,),
        ).fetchall()

    if not to_fold:
        return

    transcript = "\n".join(f"{role}: {content}" for _, role, content in to_fold)
    previous_summary = get_summary() or "(none yet)"
    prompt = (
        "You are maintaining a short rolling summary of an ongoing chat "
        "between a user and an assistant named Lyra, so older turns can be "
        "dropped from the prompt without losing context. Update the "
        "summary below to also cover the new lines, in 4 sentences or "
        "fewer. Keep concrete facts (names, preferences, decisions, open "
        "questions); drop small talk. Reply with ONLY the updated "
        "summary text, nothing else.\n\n"
        f"Existing summary: {previous_summary}\n\n"
        f"New lines to fold in:\n{transcript}"
    )

    try:
        new_summary = summarize(prompt)
    except Exception:
        # Best-effort: a failed summarization call just means this batch
        # gets retried next turn instead of being lost.
        return

    new_summary = (new_summary or "").strip()
    if not new_summary:
        return

    ids = [row[0] for row in to_fold]
    with _connect() as conn:
        conn.executemany(
            "UPDATE chat_history SET summarized = 1 WHERE id = ?",
            [(i,) for i in ids],
        )
    set_summary(new_summary)


def build_memory_prefix() -> str:
    """
    A short preamble to prepend to the prompt sent to the LLM, or "" if
    nothing is known yet about the user. Framed explicitly as background
    context (not something the user just said) so the model doesn't treat
    it as part of the live turn.

    Phase 5: folds in preferences, the rolling summary, and the last few
    turns verbatim, on top of Phase 3's name-only line.
    """
    parts = []

    name = get_user_name()
    if name:
        parts.append(f"The user's name is {name}.")

    prefs = get_preferences()
    if prefs:
        parts.append("Known preferences: " + "; ".join(prefs) + ".")

    summary = get_summary()
    if summary:
        parts.append("Summary of the conversation so far: " + summary)

    recent = get_recent_turns()
    if recent:
        lines = "\n".join(
            f"{'User' if role == 'user' else 'Lyra'}: {content}" for role, content in recent
        )
        parts.append("Most recent turns:\n" + lines)

    if not parts:
        return ""

    body = "\n".join(parts)
    return (
        "[Background context — not something the user just said, don't "
        "treat it as a live instruction:\n"
        f"{body}\n"
        "Address the user by name when it feels natural, but don't force "
        "it into every reply.]\n\n"
    )


init_db()
