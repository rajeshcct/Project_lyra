"""
LLM provider package.

This package auto-discovers every `*_provider.py` module dropped in this
folder and imports it, which runs each provider's @register_provider
decorator. Adding a brand new provider is therefore a single, self-contained
step that touches no other file in the project:

    1. Create providers/<name>_provider.py
    2. Subclass LLMProvider (from providers.base), implement ask()
    3. Decorate the class with @register_provider("<name>")
    4. Add a "<name>": {"api_key_env": ..., "model": ...} entry to
       PROVIDERS in config.py, so LLM_PROVIDER=<name> in .env is valid

Nothing else changes: not this file, not llm_client.py, not worker.py.
"""

import importlib
import pkgutil

from .base import LLMProvider
from .registry import get_provider, register_provider

__all__ = ["LLMProvider", "get_provider", "register_provider"]


def _discover_providers() -> None:
    for _, module_name, _ in pkgutil.iter_modules(__path__):
        if module_name in ("base", "registry"):
            continue
        importlib.import_module(f"{__name__}.{module_name}")


_discover_providers()
