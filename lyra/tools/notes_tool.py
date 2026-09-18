"""
Phase 14 -- write_file tool: save a note to disk.

Writing to the user's disk is exactly the "sends/deletes/modifies
something real" bar the plan's Security Considerations rule #3 sets for
requiring human confirmation (same bar as email_tool.py's send_email and
reminder_tool.py's delete_reminder/clear_reminders), so this is
registered with requires_confirmation=True: the human sees the exact
filename + content and must click Yes in main.py's dialog before
anything is actually written -- a prompt-injected instruction hidden in
a tool result or RAG document can't cause a real write without a human
approving the exact content shown (see main.py's _confirmation_prompt,
which gets a write_file-specific preview alongside send_email's).

The filename the model sends is never used as a raw path: Path(...).name
strips any directory components (no ../.. escape out of notes/), and the
extension is forced to .txt or .md, so this can only ever create a
plain-text file directly inside notes/, never overwrite something
elsewhere on disk -- same "fixed safe arguments, never a raw path/command"
shape as system_control_tool.py's app allowlist.
"""

import subprocess
from pathlib import Path

from ..paths import PROJECT_ROOT
from .base import ToolSpec
from .registry import register_tool

_NOTES_DIR = PROJECT_ROOT / "notes"
_ALLOWED_EXTENSIONS = (".txt", ".md")
_DEFAULT_EXTENSION = ".txt"


def _safe_filename(filename: str) -> str:
    name = (filename or "").strip()
    if not name:
        raise RuntimeError("No filename given.")

    # Strip any path components the model might send -- this only ever
    # writes directly inside notes/, never anywhere else on disk.
    name = Path(name).name
    if not name or name in (".", ".."):
        raise RuntimeError(f"'{filename}' isn't a valid filename.")

    stem, dot, ext = name.rpartition(".")
    if dot and ("." + ext.lower()) in _ALLOWED_EXTENSIONS:
        return name
    # No extension, or one we don't allow -- default to .txt.
    return (stem if dot else name) + _DEFAULT_EXTENSION


def write_file(filename: str, content: str) -> str:
    """Save `content` as a .txt/.md file inside notes/ and open it."""
    safe_name = _safe_filename(filename)

    try:
        _NOTES_DIR.mkdir(parents=True, exist_ok=True)
        path = _NOTES_DIR / safe_name
        path.write_text(content or "", encoding="utf-8")
    except Exception as e:
        raise RuntimeError(f"Could not save '{safe_name}': {e}") from e

    try:
        # Explicit notepad.exe (not os.startfile) so this always opens in
        # Notepad specifically, regardless of whatever the user's default
        # .txt/.md handler happens to be.
        subprocess.Popen(["notepad.exe", str(path)])
    except Exception:
        pass  # saving is the part that matters -- opening it is a convenience

    return f"Saved '{safe_name}' to the notes folder and opened it in Notepad."


register_tool(
    ToolSpec(
        name="write_file",
        description=(
            "Save text content as a .txt or .md file inside the notes/ "
            "folder and open it in Notepad. Use when the user explicitly "
            "asks you to write, save, or note something down to a file "
            "(e.g. a list, draft, or set of instructions). Write the full, "
            "finished content yourself -- the user will see and must "
            "approve the exact filename and content before anything is "
            "actually written to disk, so don't tell them it's saved "
            "unless this tool's own result confirms it."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name for the file, e.g. 'shopping_list.txt' or 'ideas.md'. A .txt extension is added automatically if omitted.",
                },
                "content": {
                    "type": "string",
                    "description": "The full text content to save.",
                },
            },
            "required": ["filename", "content"],
        },
        func=write_file,
        # Security rule #3 -- writes real data to the user's disk, same
        # confirmation bar as send_email / delete_reminder.
        requires_confirmation=True,
    )
)
