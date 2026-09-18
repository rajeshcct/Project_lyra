"""
Tool package.

Phase 13 fix -- this used to auto-discover every `*_tool.py` module in
this folder via pkgutil.iter_modules(__path__), which works fine running
from source but finds NOTHING in a PyInstaller-frozen build (bundled
modules live inside the .exe's PYZ archive, not as real files in a real
directory to scan). Same bug as providers/__init__.py's groq/gemini
discovery, just quieter here -- every tool (weather, reminders, email,
RAG, system control, calculator, web search) would silently fail to
register, leaving the LLM with zero tools in the packaged app instead of
a visible startup error.

Tools are now imported explicitly by name below. Adding a new tool is
still simple, just one extra step versus before:

    1. Create tools/<name>_tool.py
    2. Write a plain function that does the work and returns a string
       (raise RuntimeError on failure -- never let a raw exception escape)
    3. Build a ToolSpec (name, description, JSON-schema parameters, func)
       and call register_tool(spec) at module level
    4. Add `from . import <name>_tool  # noqa: F401` below

Nothing else changes: not this file's exports, not llm_client.py, not
the provider implementations, not worker.py or main.py.
"""

from .base import ToolSpec, TOOL_SAFETY_SYSTEM_PROMPT
from .registry import register_tool, get_tool, get_all_tools

__all__ = [
    "ToolSpec",
    "TOOL_SAFETY_SYSTEM_PROMPT",
    "register_tool",
    "get_tool",
    "get_all_tools",
]

# Explicit imports (not pkgutil auto-discovery -- see module docstring
# above) run each module's register_tool() call as a side effect.
from . import calculator_tool  # noqa: F401
from . import weather_tool  # noqa: F401
from . import websearch_tool  # noqa: F401
from . import reminder_tool  # noqa: F401
from . import email_tool  # noqa: F401
from . import rag_tool  # noqa: F401
from . import system_control_tool  # noqa: F401
