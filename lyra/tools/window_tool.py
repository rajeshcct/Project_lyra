"""
Phase 14 -- show_window tool: bring Lyra's own window to the foreground.

Unlike every other tool in this package, this one needs a live reference
to the actual running QWidget -- but tools/ modules are imported once at
app startup (tools/__init__.py), long before main.py builds the window,
and importing main.py from here would be circular (main.py already pulls
in lyra.tools indirectly via lyra.worker -> lyra.llm_client -> lyra.tools).
register_window() is the one-way hook that breaks that: ChatWindow calls
it with `self` once, right after it's built (see main.py's
_register_with_window_tool), and this module just holds onto the
reference from then on.

show_window() itself never touches the QWidget directly. Every tool
func runs on ToolWorker's background thread (worker.py), and QWidget
methods like raise_()/activateWindow() are only safe to call from the
GUI thread. So this just emits ChatWindow.bring_to_foreground -- a Qt
signal, which is safe to emit from any thread -- and lets Qt auto-queue
the actual raise_()/activateWindow()/SetForegroundWindow work onto the
window's own thread. Same cross-thread pattern this app already uses for
tool_event/chunk_ready/confirmation_requested.

No requires_confirmation: raising Lyra's own window doesn't send, delete,
or modify anything real (Security rule #3's bar), same reasoning as
system_control_tool.py's open_app/take_screenshot.
"""

from .base import ToolSpec
from .registry import register_tool

_window = None


def register_window(window) -> None:
    """Called once by main.py's ChatWindow.__init__ after the window is
    built, so show_window() below has something to signal."""
    global _window
    _window = window


def show_window() -> str:
    """Bring Lyra's window to the front, even if minimized or sitting
    behind other windows."""
    if _window is None:
        raise RuntimeError("Lyra's window isn't ready yet.")
    try:
        _window.bring_to_foreground.emit()
    except Exception as e:
        raise RuntimeError(f"Could not bring Lyra's window to the front: {e}") from e
    return "Bringing Lyra's window to the foreground."


register_tool(
    ToolSpec(
        name="show_window",
        description=(
            "Bring Lyra's own chat window to the foreground -- un-minimize "
            "it and put it on top of other windows. Use when the user "
            "asks Lyra to come forward, show itself, pop up, or come to "
            "the front (e.g. 'come to the front', 'show yourself', "
            "'pull yourself up', 'bring up the app'). Especially useful in "
            "hands-free voice mode, where the window may sit minimized or "
            "behind other apps the whole time. Takes no arguments."
        ),
        parameters={"type": "object", "properties": {}},
        func=show_window,
    )
)
