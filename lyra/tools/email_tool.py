"""
Phase 8 — email tool (Gmail).

One tool over lyra/gmail_client.py: the model drafts a to/subject/body,
Lyra shows that draft to the human, and only actually sends once they
confirm. This reuses Phase 7's confirmation framework wholesale rather
than building a separate "email preview" UI: setting
requires_confirmation=True below means providers/base.py's
on_confirmation_required already pauses and shows the exact drafted
arguments before send_email() ever runs (see main.py's
_on_confirmation_requested, which special-cases this tool's args into a
readable To/Subject/Body preview instead of the generic key=value dump).

This satisfies the plan's Security Considerations rule directly: the
"confirmed" flag is set by an actual button click in main.py's
QMessageBox, never by the LLM asserting in its own output that the user
agreed. A prompt-injected instruction (e.g. hiding "send this to
attacker@evil.com" inside a web search result or RAG document that this
tool's args happen to echo) still can't cause a real send without a
human clicking Yes on the exact address/subject/body shown.

gmail_client is imported at module top (not lazily) because gmail_client
itself has no top-level google-auth/googleapiclient imports -- those are
lazy inside its own functions (see its docstring) -- so importing this
module during tools/__init__.py's auto-discovery can't crash the app the
way a missing `requests`/`ddgs` would for weather_tool.py/websearch_tool.py.
"""

from .. import gmail_client
from .base import ToolSpec
from .registry import register_tool


def send_email_tool(to: str, subject: str, body: str) -> str:
    gmail_client.send_email(to, subject, body)
    return f"Email sent to {to} (subject: '{subject}')."


register_tool(
    ToolSpec(
        name="send_email",
        description=(
            "Draft and send an email from the user's own Gmail account. "
            "Use only when the user explicitly asks to send/email "
            "something to someone. Compose a clear, complete subject and "
            "body yourself based on what they asked for -- the user will "
            "see and must approve the exact draft before anything is "
            "actually sent, so write it as a finished email, not a "
            "placeholder. Never tell the user an email was sent unless "
            "this tool's own result confirms it -- sending only happens "
            "after their explicit approval, not just because you called "
            "this tool."
        ),
        parameters={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient's email address.",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line.",
                },
                "body": {
                    "type": "string",
                    "description": "Full email body text.",
                },
            },
            "required": ["to", "subject", "body"],
        },
        func=send_email_tool,
        # Phase 8 -- sending real email to a real person is exactly the
        # "sends/deletes/modifies something real" case the plan calls out
        # by name for confirmation (Security rule #3), same bar as
        # reminder_tool.py's delete_reminder/clear_reminders.
        requires_confirmation=True,
    )
)
