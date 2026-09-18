"""
Phase 8 — Gmail API client (OAuth + send).
--------------------------------------------
Plain, headless module: zero PySide6 import, zero provider-SDK import,
same "reusable from a CLI or the GUI without changes" rule as
memory.py/reminders.py/llm_client.py. tools/email_tool.py is the only
thing that calls into this file.

Auth model (per the plan): **Desktop app OAuth credential type** — this
opens the user's system browser for a one-time consent screen instead of
needing a web redirect URI, which is the simpler flow for a desktop app.
Scope is `gmail.send` only, the minimum needed to compose-and-send; this
app never reads, lists, or deletes anything in the user's mailbox.

Two files live in the project root, both gitignored (see .gitignore):
  - credentials.json  — the OAuth client secret downloaded once from
                         Google Cloud Console (see README's "Gmail setup"
                         section for the exact steps). Identifies *this
                         app* to Google, not any particular user.
  - token.json         — created automatically after the first successful
                         login. Holds this user's access/refresh token so
                         they aren't sent through the browser flow again
                         on every run. Treat it like a password: anyone
                         holding it can send email as the logged-in user
                         (see plan's Security Considerations, Credential
                         handling).

Every google-auth / googleapiclient import below is lazy (inside
functions, not at module top) for the same reason weather_tool.py and
websearch_tool.py do it: tools/__init__.py auto-imports every tool module
(and this module, via email_tool.py) at app startup, so a missing
dependency here would otherwise crash the whole app instead of just
email-related tool calls.
"""

import base64
from email.mime.text import MIMEText
from typing import Optional

from .paths import PROJECT_ROOT as _PROJECT_ROOT

# Minimum viable scope — send only. Never widen this to gmail.readonly /
# gmail.modify / etc. without a real reason; the smaller the scope, the
# smaller the blast radius if token.json ever leaks.
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

CREDENTIALS_PATH = _PROJECT_ROOT / "credentials.json"
TOKEN_PATH = _PROJECT_ROOT / "token.json"

_service = None  # cached across calls within one process run


def _load_credentials():
    """Return valid google.oauth2.credentials.Credentials, running the
    browser-based OAuth flow (and writing token.json) only if needed —
    i.e. first-ever run, or an existing token that can't be silently
    refreshed. Every subsequent call in the same process, and every
    later app run, reuses token.json without touching the browser."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:
        raise RuntimeError(
            "Gmail support needs a few extra packages. Run "
            "'pip install -r requirements.txt' (google-api-python-client, "
            "google-auth-httplib2, google-auth-oauthlib) to enable email."
        ) from e

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
            return creds
        except Exception:
            # Refresh token itself got revoked/expired -- fall through and
            # redo the full interactive flow rather than failing outright.
            creds = None

    if not CREDENTIALS_PATH.exists():
        raise RuntimeError(
            "No Gmail credentials.json found in the project folder. "
            "See the README's 'Gmail setup' section: download an OAuth "
            "client (type 'Desktop app') from Google Cloud Console and "
            f"save it as {CREDENTIALS_PATH}."
        )

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
        # Opens the system browser for a one-time consent screen (plan's
        # "simpler than a web redirect URI" reasoning). port=0 picks any
        # free local port for the loopback redirect. This blocks the
        # calling thread until the user finishes in the browser -- fine
        # here since send_email() always runs on ToolWorker's background
        # thread (see worker.py), never the GUI thread.
        creds = flow.run_local_server(port=0)
    except Exception as e:
        raise RuntimeError(f"Gmail sign-in failed or was cancelled: {e}") from e

    TOKEN_PATH.write_text(creds.to_json())
    return creds


def _get_service():
    global _service
    if _service is not None:
        return _service

    try:
        from googleapiclient.discovery import build
    except ImportError as e:
        raise RuntimeError(
            "Gmail support needs 'google-api-python-client'. Run "
            "'pip install -r requirements.txt' to enable email."
        ) from e

    creds = _load_credentials()
    try:
        _service = build("gmail", "v1", credentials=creds)
    except Exception as e:
        raise RuntimeError(f"Could not start the Gmail API client: {e}") from e
    return _service


def send_email(to: str, subject: str, body: str, sender: Optional[str] = None) -> str:
    """Send a plain-text email via the signed-in user's Gmail account.
    Returns the sent message's Gmail id. Raises RuntimeError on any
    failure (missing credentials, network error, invalid address, API
    error) -- same contract as every ToolSpec.func in this project."""
    to = (to or "").strip()
    if not to:
        raise RuntimeError("No recipient address given.")

    service = _get_service()

    message = MIMEText(body or "")
    message["to"] = to
    message["subject"] = subject or "(no subject)"
    if sender:
        message["from"] = sender

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    try:
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    except Exception as e:
        raise RuntimeError(f"Gmail refused to send the message: {e}") from e

    return sent.get("id", "")
