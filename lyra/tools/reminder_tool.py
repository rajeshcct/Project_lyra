"""
Phase 5 — reminders tool.

Three small tools over lyra/reminders.py's SQLite-backed list: add one,
list what's outstanding, and mark one done. See reminders.py's module
docstring for the scope note — this is a persisted to-do list the model
can read/write, not a scheduler that pushes alerts at a specific time.

None of these touch the OS, the network, or anything outside Lyra's own
db file, so none of them set requires_confirmation — same "harmless,
no-OS-access" bar the calculator tool sets in calculator_tool.py.
"""

from .. import reminders
from .base import ToolSpec
from .registry import register_tool


def add_reminder(text: str, remind_at: str = "") -> str:
    reminder_id = reminders.add_reminder(text, remind_at or None)
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
            "something they were reminded about, or asks to clear/remove "
            "a specific reminder."
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
