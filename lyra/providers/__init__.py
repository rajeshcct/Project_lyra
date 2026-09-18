"""
LLM provider package.

Phase 13 fix -- this used to auto-discover every `*_provider.py` module in
this folder via pkgutil.iter_modules(__path__), which works fine running
from source but finds NOTHING in a PyInstaller-frozen build: bundled
modules live inside the .exe's PYZ archive, not as real files in a real
directory a filesystem scan can list. That's exactly the
"No provider implementation registered for 'groq'. Available: (none
discovered)" error the packaged .exe hit -- pkgutil silently found zero
provider modules, not just groq_provider specifically.

Providers are now imported explicitly by name below. Adding a new
provider is still simple, just one extra step versus before:

    1. Create providers/<name>_provider.py
    2. Subclass LLMProvider (from providers.base), implement ask()
    3. Decorate the class with @register_provider("<name>")
    4. Add a "<name>": {...} entry to PROVIDERS in config.py
    5. Add `from . import <name>_provider  # noqa: F401` below

Nothing else changes: not this file's exports, not llm_client.py, not
worker.py.
"""

from .base import LLMProvider
from .registry import get_provider, register_provider

# Explicit imports (not pkgutil auto-discovery -- see module docstring
# above) run each module's @register_provider decorator as a side effect.
from . import groq_provider  # noqa: F401
from . import gemini_provider  # noqa: F401

__all__ = ["LLMProvider", "get_provider", "register_provider"]
