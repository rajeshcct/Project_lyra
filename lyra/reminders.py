"""
Phase 5 — reminders storage (SQLite).
--------------------------------------
Same pattern as memory.py: plain sqlite3 (stdlib), zero PySide6 import,
zero provider-SDK import, reusable from a CLI or the GUI without changes.
Lives in the same lyra_memory.db file as the users/chat_history tables
(one db file for the whole app, per the existing DB_PATH convention) but
gets its own module rather than being folded into memory.py, since
reminders are a distinct concern from personal-memory/context.

Original scope note (Phase 5): this started as a *list*, not an alarm
clock -- `remind_at` was stored as whatever free-text the user said and
only ever surfaced back when asked.

Phase 7 (scheduler) changes that: `add_reminder()` now also tries to
parse `remind_at` into an absolute, timezone-aware `scheduled_at` (UTC
ISO string) via the `dateparser` package -- lazily imported, same "don't
crash the whole app over one missing dependency" reasoning as
weather_tool.py/websearch_tool.py. If parsing fails (vague phrasing like
"sometime later", or `dateparser` not installed), `scheduled_at` stays
NULL and the reminder behaves exactly as before: list-only, no alarm.
When it does parse, `lyra/scheduler.py`'s background poller can actually
find and fire it.

Phase 8 adds `email_to` / `email_body` / `email_sent`: an optional email
to send automatically when the reminder fires, on top of the system
notification -- see tools/reminder_tool.py's `add_email_reminder` (the
confirmation-gated tool that sets these) and scheduler.py (what actually
sends it).
"""

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .paths import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / "lyra_memory.db"

# Phase 11 fix -- eagerly (pre-)import dateparser here, at module load time
# on the MAIN thread (reminders.py is imported during tools/__init__.py's
# auto-discovery at app startup, before any QThread exists), so
# _parse_schedule()'s own `import dateparser` later just hits an
# already-populated sys.modules cache instead of importing it for the
# first time from a background QThread.
#
# Catching plain Exception here (not just ImportError) is deliberate and
# was widened after this surfaced a real environment bug: on this
# machine's Python 3.12 + installed `six` version, importing dateparser
# can itself raise "AttributeError: '_SixMetaPathImporter' object has no
# attribute '_path'" -- a known six/Python-3.12 importlib incompatibility
# (six's meta path finder predates import-protocol changes 3.12 tightened),
# not a normal "package missing" case. Narrowing this to ImportError
# turned a one-feature failure (reminders just wouldn't get a schedule)
# into a whole-app startup crash the moment this module loaded. The real
# fix is upgrading/reinstalling `six` in the venv (`pip install --upgrade
# six`) -- this except is a safety net so a broken `six` degrades to
# "reminders save without a schedule" instead of the app not starting.
try:
    import dateparser  # noqa: F401
except Exception:
    pass


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, coltype: str) -> None:
    """Add `column` to `table` if it isn't there yet. Same migration-safe
    helper as memory.py's -- SQLite has no 'ADD COLUMN IF NOT EXISTS', so
    check pragma table_info first. Keeps init_db() safe to call on both a
    fresh Phase 7/8 db and an existing Phase 5 db that predates these
    columns."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db() -> None:
    """Create the reminders table if it doesn't exist yet, and migrate an
    older db forward. Safe to call every startup — same convention as
    memory.init_db()."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                remind_at TEXT,           -- free-text as the user said it
                done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        # Phase 7 (scheduler) migrations.
        _ensure_column(conn, "reminders", "scheduled_at", "TEXT")  # UTC ISO, NULL if unparseable
        _ensure_column(conn, "reminders", "notified", "INTEGER NOT NULL DEFAULT 0")
        # Phase 8 migrations.
        _ensure_column(conn, "reminders", "email_to", "TEXT")
        _ensure_column(conn, "reminders", "email_body", "TEXT")
        _ensure_column(conn, "reminders", "email_sent", "INTEGER NOT NULL DEFAULT 0")


def _parse_schedule(remind_at: str) -> Optional[str]:
    """Best-effort: turn a free-text time expression ("in 2 minutes",
    "tomorrow at 5pm", "next Friday at noon") into an absolute UTC ISO
    datetime string the scheduler can compare against. Returns None if no
    usable date/time is found, if `dateparser` isn't installed, or if
    dateparser itself raises on unusual input (e.g. missing tzdata) --
    the reminder is still saved either way, it just won't trigger anything
    on its own (see module docstring). This used to only catch ImportError,
    which let a raw dateparser exception escape all the way up through
    tools/reminder_tool.py's add_reminder() with no try/except of its own --
    violating this project's own tools/base.py contract ("never let a raw
    exception escape") and surfacing as a generic "unexpected error" to
    the user instead of the reminder just saving without a schedule."""
    try:
        import dateparser
    except ImportError:
        return None

    try:
        parsed = dateparser.parse(
            remind_at,
            settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": True},
        )
        if parsed is None:
            return None
        # Naive datetimes' .astimezone() assumes the system's local timezone
        # first, then converts -- correct behavior whether dateparser handed
        # back an aware or naive result.
        return parsed.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def add_reminder(
    text: str,
    remind_at: Optional[str] = None,
    email_to: Optional[str] = None,
    email_body: Optional[str] = None,
) -> int:
    """Store a reminder and return its id. `email_to`/`email_body` are
    Phase 8 additions -- see tools/reminder_tool.py's add_email_reminder,
    the only caller that ever passes them (plain add_reminder never does)."""
    now = datetime.now(timezone.utc).isoformat()
    scheduled_at = _parse_schedule(remind_at) if remind_at else None
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO reminders (text, remind_at, scheduled_at, email_to, email_body, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (text, remind_at, scheduled_at, email_to, email_body, now),
        )
        return cursor.lastrowid


def get_reminder(reminder_id: int) -> Optional[dict]:
    """A single reminder's full row, or None if it doesn't exist."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, text, remind_at, scheduled_at, email_to, email_body, "
            "email_sent, done, created_at FROM reminders WHERE id = ?",
            (reminder_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "text": row[1],
        "remind_at": row[2],
        "scheduled_at": row[3],
        "email_to": row[4],
        "email_body": row[5],
        "email_sent": bool(row[6]),
        "done": bool(row[7]),
        "created_at": row[8],
    }


def list_reminders(include_done: bool = False) -> list[dict]:
    """All reminders, most recently created first."""
    query = "SELECT id, text, remind_at, scheduled_at, email_to, done, created_at FROM reminders"
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
            "scheduled_at": row[3],
            "email_to": row[4],
            "done": bool(row[5]),
            "created_at": row[6],
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


# Phase 7 -- unlike complete_reminder() above (which just flags a row done
# and leaves it recoverable/visible with include_done=True), these two
# permanently remove rows. That's what makes them worth a confirmation
# prompt at the tool layer (see tools/reminder_tool.py) rather than being
# harmless like the rest of this module.
def delete_reminder(reminder_id: int) -> bool:
    """Permanently delete one reminder. Returns True if a row was removed."""
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        return cursor.rowcount > 0


def clear_reminders() -> int:
    """Permanently delete every outstanding (not-done) reminder. Returns
    how many rows were removed."""
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM reminders WHERE done = 0")
        return cursor.rowcount


# --- Phase 7 (scheduler) -----------------------------------------------

def get_due_reminders() -> list[dict]:
    """Reminders whose scheduled_at has passed, aren't done, and haven't
    already been notified about. This is what lyra/scheduler.py's
    background poll calls every ~60s -- see its module docstring for the
    full cross-thread design."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, text, email_to, email_body, email_sent
            FROM reminders
            WHERE done = 0 AND notified = 0
              AND scheduled_at IS NOT NULL AND scheduled_at <= ?
            """,
            (now,),
        ).fetchall()
    return [
        {
            "id": row[0],
            "text": row[1],
            "email_to": row[2],
            "email_body": row[3],
            "email_sent": bool(row[4]),
        }
        for row in rows
    ]


def mark_notified(reminder_id: int) -> None:
    with _connect() as conn:
        conn.execute("UPDATE reminders SET notified = 1 WHERE id = ?", (reminder_id,))


def mark_email_sent(reminder_id: int) -> None:
    with _connect() as conn:
        conn.execute("UPDATE reminders SET email_sent = 1 WHERE id = ?", (reminder_id,))


init_db()
