"""
Tool registry.

Same plain name -> spec lookup pattern as providers/registry.py. Tool
modules register themselves via register_tool() when imported (see the
auto-discovery in tools/__init__.py). This file has zero knowledge of
which tools actually exist.
"""

from .base import ToolSpec

_REGISTRY: dict[str, ToolSpec] = {}


def register_tool(spec: ToolSpec) -> None:
    """Register a ToolSpec so it's included in every tool-enabled LLM call."""
    _REGISTRY[spec.name] = spec


def get_tool(name: str) -> ToolSpec:
    try:
        return _REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY)) or "(none discovered)"
        raise RuntimeError(f"No tool named '{name}'. Available: {available}")


def get_all_tools() -> list[ToolSpec]:
    """All registered tools, for handing to a provider's ask_with_tools()."""
    return list(_REGISTRY.values())
