"""
Phase 5 — reminders tool.

Five tools over lyra/reminders.py's SQLite-backed list: add one, list
what's outstanding, mark one done, delete one, or clear all outstanding
ones. See reminders.py's module docstring for the scope note — this is
a persisted to-do list the model can read/write, not a scheduler that
pushes alerts at a specific time.

add_reminder/list_reminders/complete_reminder don't touch the OS, the
network, or anything outside Lyra's own db file, and complete_reminder is
recoverable (the row still exists, just flagged done) — same "harmless"
bar the calculator tool sets in calculator_tool.py, so none of those three
set requires_confirmation.

delete_reminder/clear_reminders are different: they permanently remove
rows with no undo. Phase 7 — these are Lyra's first tools to actually set
requires_confirmation=True, exercising the confirm/deny flow that
providers/base.py's on_confirmation_required plumbs through to the UI
(see main.py's _on_confirmation_requested for the dialog itself).
"""

from .. import reminders
from .base import ToolSpec
from .registry import register_tool


def add_reminder(text: str, remind_at: str = "") -> str:
    try:
        reminder_id = reminders.add_reminder(text, remind_at or None)
    except Exception as e:
        # Defense in depth on top of reminders.py's own _parse_schedule fix
        # -- a raw exception (DB-level or otherwise) must never escape a
        # tool func per tools/base.py's contract, or it surfaces to the
        # user as an opaque "unexpected error" instead of something
        # actionable.
        raise RuntimeError(f"Could not save the reminder: {e}") from e
    when = f" ({remind_at})" if remind_at else ""
    return f"Reminder #{reminder_id} saved: {text}{when}"


def list_reminders() -> str:
    items = reminders.list_reminders(include_done=False)
    if not items:
        return "No outstanding reminders."
    lines = []
    for item in items:
        when = f" — {item['remind_at']}" if item["remind_at"] else ""
        lines.append(f"#{item['id']}: {item['text']}{when}")
    return "\n".join(lines)


def complete_reminder(reminder_id: int) -> str:
    ok = reminders.complete_reminder(reminder_id)
    if not ok:
        raise RuntimeError(f"No reminder found with id {reminder_id}.")
    return f"Reminder #{reminder_id} marked done."


def delete_reminder(reminder_id: int) -> str:
    ok = reminders.delete_reminder(reminder_id)
    if not ok:
        raise RuntimeError(f"No reminder found with id {reminder_id}.")
    return f"Reminder #{reminder_id} permanently deleted."


def clear_reminders() -> str:
    count = reminders.clear_reminders()
    if count == 0:
        return "No outstanding reminders to clear."
    return f"Deleted {count} outstanding reminder(s)."


# Phase 8 -- the "wire it into Phase 7's reminder scheduler" step the plan
# calls for. Unlike plain add_reminder (list-only, no alarm), this one
# needs a genuinely parseable time, since scheduler.py can only fire an
# email against a real scheduled_at, not free-text like "sometime later".
def add_email_reminder(text: str, remind_at: str, email_to: str, email_body: str = "") -> str:
    remind_at = (remind_at or "").strip()
    email_to = (email_to or "").strip()
    if not remind_at:
        raise RuntimeError(
            "An email reminder needs a specific time, e.g. 'in 10 minutes' "
            "or 'tomorrow at 9am' -- vague phrasing can't be scheduled."
        )
    if not email_to:
        raise RuntimeError("An email reminder needs a recipient email address.")

    reminder_id = reminders.add_reminder(
        text, remind_at, email_to=email_to, email_body=email_body or text
    )
    saved = reminders.get_reminder(reminder_id)
    if not saved or not saved["scheduled_at"]:
        # add_reminder() saves it either way (see reminders.py), but an
        # email reminder with no parseable schedule would just sit there
        # forever with nothing to trigger it -- better to tell the model/
        # user now than leave a silently-dead email promise behind.
        reminders.delete_reminder(reminder_id)
        raise RuntimeError(
            f"Couldn't understand '{remind_at}' as a specific time, so no "
            "email reminder was scheduled. Try something like 'in 20 "
            "minutes' or 'tomorrow at 5pm'."
        )
    return (
        f"Reminder #{reminder_id} saved: '{text}'. Lyra will notify you and "
        f"email {email_to} when it's due ({remind_at})."
    )


register_tool(
    ToolSpec(
        name="add_reminder",
        description=(
            "Save a reminder for the user to look at later. Use whenever "
            "the user asks to be reminded of something or to add something "
            "to a to-do/reminder list. This does not set an alarm or send "
            "a notification at a specific time — it just saves the "
            "reminder so it can be listed later with list_reminders."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "What to be reminded about, e.g. 'call the dentist'.",
                },
                "remind_at": {
                    "type": "string",
                    "description": (
                        "Optional free-text time/date the user mentioned, e.g. "
                        "'tomorrow at 5pm' or 'next Friday'. Leave empty if the "
                        "user didn't give a time."
                    ),
                },
            },
            "required": ["text"],
        },
        func=add_reminder,
    )
)

register_tool(
    ToolSpec(
        name="list_reminders",
        description=(
            "List the user's outstanding (not-yet-completed) reminders. "
            "Use when the user asks what they're supposed to remember, "
            "what's on their reminder/to-do list, or similar."
        ),
        parameters={"type": "object", "properties": {}},
        func=list_reminders,
    )
)

register_tool(
    ToolSpec(
        name="complete_reminder",
        description=(
            "Mark a reminder as done, given its id number (shown by "
            "list_reminders). Use when the user says they've done "
            "something they were reminded about. This keeps the reminder "
            "around (just flagged done) -- use delete_reminder instead if "
            "the user wants it actually removed."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "integer",
                    "description": "The id number of the reminder, as shown by list_reminders.",
                }
            },
            "required": ["reminder_id"],
        },
        func=complete_reminder,
    )
)

# Phase 7 -- the first two tools in this file to set requires_confirmation.
# Unlike complete_reminder above, these permanently remove data with no
# undo, so both providers will pause and ask the user to approve/deny
# before running func (see providers/base.py's on_confirmation_required).
register_tool(
    ToolSpec(
        name="delete_reminder",
        description=(
            "Permanently delete a single reminder, given its id number "
            "(shown by list_reminders). Use when the user explicitly asks "
            "to delete or remove a specific reminder, as opposed to just "
            "marking it done."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "integer",
                    "description": "The id number of the reminder, as shown by list_reminders.",
                }
            },
            "required": ["reminder_id"],
        },
        func=delete_reminder,
        requires_confirmation=True,
    )
)

register_tool(
    ToolSpec(
        name="clear_reminders",
        description=(
            "Permanently delete every outstanding reminder. Use only when "
            "the user explicitly asks to clear, wipe, or delete their "
            "entire reminder list -- not for completing or removing a "
            "single reminder."
        ),
        parameters={"type": "object", "properties": {}},
        func=clear_reminders,
        requires_confirmation=True,
    )
)

# Phase 8 -- sets up a real automatic email send that fires later, 
# unattended, from scheduler.py once the reminder comes due. The human
# has no second chance to catch a bad address/draft at send time the way
# send_email's confirmation works, so the confirmation has to happen right
# here at setup time instead -- same Security rule #3 the plan calls out
# by name for email, just applied at creation instead of at send.
register_tool(
    ToolSpec(
        name="add_email_reminder",
        description=(
            "Save a reminder that fires at a specific time and ALSO sends "
            "an email automatically when it's due, on top of the normal "
            "system notification. Use only when the user explicitly asks "
            "to be emailed/notified-by-email about something at a given "
            "time -- for a plain reminder with no email, use add_reminder "
            "instead. Requires a real, specific time (e.g. 'in 10 "
            "minutes', 'tomorrow at 9am') since the email can only be "
            "scheduled against an actual point in time, not vague "
            "phrasing like 'sometime later'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "What the reminder is about, e.g. 'stand-up meeting'.",
                },
                "remind_at": {
                    "type": "string",
                    "description": (
                        "When to fire, as a specific time/date expression, "
                        "e.g. 'in 30 minutes' or 'tomorrow at 5pm'."
                    ),
                },
                "email_to": {
                    "type": "string",
                    "description": "Email address to notify when the reminder fires.",
                },
                "email_body": {
                    "type": "string",
                    "description": (
                        "Optional email body text. Defaults to the reminder "
                        "text itself if left empty."
                    ),
                },
            },
            "required": ["text", "remind_at", "email_to"],
        },
        func=add_email_reminder,
        requires_confirmation=True,
    )
)
