"""
Phase 14 -- get_datetime tool.

Simple, no-argument, no-dependency tool -- see base.py's ToolSpec
docstring for why this is worth having at all: the model has no reliable
sense of "now" on its own (it can only guess from its training cutoff),
so anything time-relative ("what day is it", "how long until Friday")
needs a real answer from the OS clock instead of a guess.
"""

from datetime import datetime

from .base import ToolSpec
from .registry import register_tool


def get_datetime() -> str:
    """Return the current local date, time, and day of the week."""
    now = datetime.now()
    return now.strftime("It is %A, %B %d, %Y, %I:%M %p.")


register_tool(
    ToolSpec(
        name="get_datetime",
        description=(
            "Get the current local date, time, and day of the week. Use "
            "this whenever the user asks what time or day it is, or "
            "whenever knowing 'now' matters for the answer -- never guess "
            "the current date/time yourself. Takes no arguments."
        ),
        parameters={"type": "object", "properties": {}},
        func=get_datetime,
    )
)
