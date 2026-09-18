"""
Phase 10 — system control tool.

Two tools: open_app(app_name) and take_screenshot(). This is the tool
the plan's Security Considerations section warns about by name, so the
allowlist is the *entire* mitigation, not an afterthought:

    "Never write a tool like run_command(cmd: str) that forwards
    LLM-generated strings straight to subprocess.run(). Fixed function
    names and fixed safe arguments only, no raw command strings from the
    model, ever." (Security rule #2 / Phase 4 rule #2)

Concretely: open_app() takes a single short `app_name` string, but that
string is only ever used as a *lookup key* into _ALLOWED_APPS below --
it is never interpolated into a command string or passed to a shell.
Anything not already a key in that dict is rejected before subprocess
is touched at all. Adding a new allowlisted app later means adding one
line to _ALLOWED_APPS, never loosening this function's logic.

No requires_confirmation on either tool: unlike email_tool.py/
reminder_tool.py's delete/clear/send, opening an already-installed,
already-trusted local application or reading the current screen doesn't
send, delete, or modify anything real (Security rule #3's bar), so the
plan's mitigation for this phase is the allowlist itself, not a
confirmation dialog on top of it.
"""

import subprocess
from datetime import datetime

from ..paths import PROJECT_ROOT
from .base import ToolSpec
from .registry import register_tool

# Fixed argv lists only -- no shell=True, no string concatenation with
# `app_name`. `cmd /c start "" <name>` resolves via Windows' own App Paths
# registry (same mechanism as Win+R), so this works without hardcoding
# per-machine install locations for Chrome/VS Code.
_ALLOWED_APPS: dict[str, list[str]] = {
    "chrome": ["cmd", "/c", "start", "", "chrome"],
    "vscode": ["cmd", "/c", "code"],
    "notepad": ["cmd", "/c", "start", "", "notepad"],
    "spotify": ["cmd", "/c", "start", "", "spotify"],
}

_SCREENSHOTS_DIR = PROJECT_ROOT / "assets" / "screenshots"


def open_app(app_name: str) -> str:
    """Open an allowlisted desktop application by name."""
    key = (app_name or "").strip().lower()
    if key not in _ALLOWED_APPS:
        allowed = ", ".join(sorted(_ALLOWED_APPS))
        raise RuntimeError(
            f"'{app_name}' isn't an allowed app. Allowed apps: {allowed}."
        )
    try:
        subprocess.Popen(_ALLOWED_APPS[key])
    except Exception as e:
        raise RuntimeError(f"Could not open {key}: {e}") from e
    return f"Opened {key}."


def take_screenshot() -> str:
    """Capture the current screen and save it as a PNG."""
    try:
        from PIL import ImageGrab
    except ImportError as e:
        raise RuntimeError(
            "The 'Pillow' package isn't installed. Run 'pip install Pillow' "
            "(see requirements.txt) to enable screenshots."
        ) from e

    try:
        _SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        path = _SCREENSHOTS_DIR / filename
        ImageGrab.grab().save(path)
    except Exception as e:
        raise RuntimeError(f"Could not take screenshot: {e}") from e
    return f"Screenshot saved to {path}."


register_tool(
    ToolSpec(
        name="open_app",
        description=(
            "Open a desktop application. Only these exact app_name values "
            "are supported: 'chrome', 'vscode', 'notepad', 'spotify' -- any "
            "other value is rejected. Use this when the user explicitly "
            "asks to open, launch, or start one of those apps. Never "
            "invent other app names; if the user asks for an app that "
            "isn't in this list, tell them it isn't supported instead of "
            "calling this tool."
        ),
        parameters={
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "One of: 'chrome', 'vscode', 'notepad', 'spotify'.",
                }
            },
            "required": ["app_name"],
        },
        func=open_app,
    )
)

register_tool(
    ToolSpec(
        name="take_screenshot",
        description=(
            "Capture the current screen and save it as a PNG file. Use "
            "when the user explicitly asks for a screenshot of their "
            "screen. Takes no arguments."
        ),
        parameters={"type": "object", "properties": {}},
        func=take_screenshot,
    )
)
