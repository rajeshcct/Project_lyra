"""
Phase 7 (completing it) -- background reminder scheduler.
------------------------------------------------------------
The plan's Phase 7 was always two halves: (1) human-in-the-loop tool
confirmation, and (2) an APScheduler poller that actually turns
reminders.py's list into something that fires on its own. Only half 1
existed before this file (see reminder_tool.py / worker.py / main.py's
confirmation dialog) -- the README flagged half 2 as the one outstanding
piece. This module is that piece.

Design, matching the plan's checkpoint text ("APScheduler
BackgroundScheduler, polling the reminders table every ~60 seconds ...
on due reminder, trigger a system notification"):

- `BackgroundScheduler` runs `_poll()` on its own daemon thread every
  `POLL_SECONDS`. `_poll()` calls `reminders.get_due_reminders()` --
  already filtered by reminders.py to done=0, notified=0, and
  scheduled_at in the past -- so this file doesn't touch SQL directly.
- Same "plain module, zero PySide6 import at the top of the *logic*"
  discipline as memory.py/reminders.py would suggest, EXCEPT this one
  genuinely needs Qt: it has to hand results back to the GUI thread
  somehow, and a `QObject` + `Signal` is the same bridge worker.py
  already uses for tool_event/chunk_ready from ToolWorker's background
  thread. Emitting a signal from a non-Qt thread (APScheduler's thread
  pool, here) is safe and Qt auto-queues delivery to whatever thread the
  connected slot lives on -- exactly the pattern worker.py relies on for
  tool_event/confirmation_requested, just with APScheduler's thread
  standing in for a QThread this time.
- Email delivery (Phase 8's "wire it into Phase 7's reminder scheduler"
  step): a reminder only ever has `email_to` set if it was created via
  tools/reminder_tool.py's `add_email_reminder`, which is
  requires_confirmation=True -- so the human already approved *this
  specific send* at setup time (Security rule #3 satisfied then, not
  here). `_poll()` firing the actual send later, unattended, is the
  intended automation the plan describes ("due reminders can optionally
  email too"), not a new bypass of the confirmation rule.
- `apscheduler` and `gmail_client`'s heavier deps are imported lazily,
  same "don't crash the whole app over one missing dependency" reasoning
  as weather_tool.py/websearch_tool.py/gmail_client.py. If APScheduler
  isn't installed, `start()` raises RuntimeError with an install hint;
  main.py catches that and logs it instead of failing to launch --
  reminders still work as a plain list either way, they just won't
  self-fire until the dependency is there.
"""

from typing import Optional

from PySide6.QtCore import QObject, Signal

from . import reminders

# Plan's own number ("polling ... every ~60 seconds"). Not exposed via
# .env -- this is an implementation detail, not something a user tunes.
POLL_SECONDS = 60


class ReminderScheduler(QObject):
    """Owns the background poll job and re-emits what it finds as Qt
    signals so main.py's GUI-thread slots can show a system notification
    / append a transcript line / fire an email, without any of this
    module needing to know PySide6 widgets exist."""

    # {"id": int, "text": str} -- once per due reminder, always (this is
    # the plain "pop a system notification" half of Phase 7, independent
    # of whether that reminder also has an email attached).
    reminder_due = Signal(dict)

    # {"id": int, "email_to": str} -- only for reminders created via
    # add_email_reminder, only after a successful send.
    reminder_email_sent = Signal(dict)

    # {"id": int, "email_to": str, "error": str} -- send attempted and
    # failed (network drop, revoked OAuth token, etc.). Deliberately does
    # NOT mark_email_sent, so the same reminder is retried on the next
    # poll rather than silently losing the email forever -- notified is
    # still set either way (see _poll), so the system notification itself
    # never repeats even if the email keeps retrying.
    reminder_email_failed = Signal(dict)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._scheduler = None  # apscheduler.BackgroundScheduler, created lazily in start()

    def start(self) -> None:
        """Start polling. Safe to call once; a second call is a no-op
        rather than a duplicate job. Raises RuntimeError if APScheduler
        isn't installed -- see module docstring on why that's a raise,
        not a silent skip: main.py decides how to surface that, this
        module shouldn't swallow it."""
        if self._scheduler is not None:
            return

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
        except ImportError as e:
            raise RuntimeError(
                "Reminder scheduling needs APScheduler. Run "
                "'pip install -r requirements.txt' to enable reminder "
                "notifications and reminder-triggered emails."
            ) from e

        self._scheduler = BackgroundScheduler(daemon=True)
        self._scheduler.add_job(
            self._poll,
            "interval",
            seconds=POLL_SECONDS,
            id="lyra_reminder_poll",
            # Also run once immediately on startup rather than waiting a
            # full POLL_SECONDS for the first check -- matters for the
            # plan's own checkpoint ("a reminder set for 2 minutes from
            # now correctly pops... on time") when the app is launched
            # right after the reminder was set in a previous run.
            next_run_time=None,
        )
        self._scheduler.start()

    def stop(self) -> None:
        """Shut the poller down. Called from main.py's closeEvent so the
        app doesn't leave a daemon thread trying to touch a QObject whose
        Python side is already being torn down."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    # -- runs on APScheduler's own thread, not the GUI thread ------------

    def _poll(self) -> None:
        for reminder in reminders.get_due_reminders():
            # Mark notified first, before doing anything that could raise
            # (email send below) -- a flaky email send should never cause
            # the same reminder to re-pop its system notification on
            # every subsequent poll.
            reminders.mark_notified(reminder["id"])
            self.reminder_due.emit({"id": reminder["id"], "text": reminder["text"]})

            if reminder["email_to"] and not reminder["email_sent"]:
                self._send_reminder_email(reminder)

    def _send_reminder_email(self, reminder: dict) -> None:
        from . import gmail_client

        try:
            gmail_client.send_email(
                to=reminder["email_to"],
                subject=f"Reminder: {reminder['text']}",
                body=reminder["email_body"] or reminder["text"],
            )
        except Exception as e:
            self.reminder_email_failed.emit(
                {"id": reminder["id"], "email_to": reminder["email_to"], "error": str(e)}
            )
            return

        reminders.mark_email_sent(reminder["id"])
        self.reminder_email_sent.emit({"id": reminder["id"], "email_to": reminder["email_to"]})
