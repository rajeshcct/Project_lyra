"""
Phase 1 — Bare LLM Chat
-----------------------
A plain, UI-free wrapper around whichever LLM provider config.py selects.

This module has zero PySide6/GUI dependency and zero knowledge of any
specific provider's SDK — it just asks providers.get_provider() for
whatever config.py selected and calls .ask() on it. Phase 2's GUI
(worker.py / main.py) imports `ask_llm` from here unchanged — the function
doesn't know or care whether it's being called from a terminal loop or a
background thread, or which provider is behind it.

Provider + model are set in config.py — switch providers there, not here.
Provider *implementations* live in providers/ — see providers/__init__.py
for how to add a new one without touching this file.
"""

from config import PROVIDER, MODEL_NAME, API_KEY
from providers import get_provider


def ask_llm(prompt: str) -> str:
    """
    Send one text prompt to the configured provider and return the reply text.

    Raises RuntimeError (never the raw SDK exception) with a human-readable
    message, so callers — the Phase 1 CLI or the Phase 2 GUI thread — can
    just catch RuntimeError and show it.
    """
    if not prompt or not prompt.strip():
        return "Say something and I'll respond."

    provider = get_provider(PROVIDER, api_key=API_KEY, model_name=MODEL_NAME)
    return provider.ask(prompt)


def ask_llm_stream(prompt: str):
    """
    Send one text prompt to the configured provider and yield reply text
    chunks as they arrive, instead of waiting for the full reply.

    Same RuntimeError contract as ask_llm: callers only ever need to catch
    RuntimeError, never a raw SDK exception.
    """
    if not prompt or not prompt.strip():
        yield "Say something and I'll respond."
        return

    provider = get_provider(PROVIDER, api_key=API_KEY, model_name=MODEL_NAME)
    yield from provider.ask_stream(prompt)
