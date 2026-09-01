"""
Tool package — auto-discovery, same pattern as providers/__init__.py.

Every `*_tool.py` module dropped in this folder gets imported automatically,
which runs its register_tool() call. Adding a new tool (Phase 5's weather,
web search, reminders, ...) is therefore a single self-contained step:

    1. Create tools/<name>_tool.py
    2. Write a plain function that does the work and returns a string
       (raise RuntimeError on failure — never let a raw exception escape)
    3. Build a ToolSpec (name, description, JSON-schema parameters, func)
       and call register_tool(spec) at module level

Nothing else changes: not this file, not llm_client.py, not the provider
implementations, not worker.py or main.py.
"""

import importlib
import pkgutil

from .base import ToolSpec, TOOL_SAFETY_SYSTEM_PROMPT
from .registry import register_tool, get_tool, get_all_tools

__all__ = [
    "ToolSpec",
    "TOOL_SAFETY_SYSTEM_PROMPT",
    "register_tool",
    "get_tool",
    "get_all_tools",
]


def _discover_tools() -> None:
    for _, module_name, _ in pkgutil.iter_modules(__path__):
        if module_name in ("base", "registry"):
            continue
        importlib.import_module(f"{__name__}.{module_name}")


_discover_tools()
