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

Phase 5 note: every entry point below now also runs
memory.maybe_condense_history() after logging the user's turn, passing in
this provider's own `.ask` as the summarizing call (see memory.py's
docstring for why it takes a plain callable instead of importing
providers/ itself). This is a no-op almost every turn — it only actually
calls the LLM again once enough old history has piled up — so it doesn't
meaningfully change latency or cost on a normal turn.
"""

from typing import Callable, Optional

from .config import PROVIDER, MODEL_NAME, API_KEY
from .providers import get_provider
from .providers.base import ToolEventCallback
from .tools import get_all_tools, TOOL_SAFETY_SYSTEM_PROMPT
from . import memory


def _extract_facts(prompt: str) -> None:
    """Shared Phase 3/5 bookkeeping: extract a name and/or preference if
    this message explicitly states one. Deliberately run BEFORE
    build_memory_prefix() and log_message() below -- build_memory_prefix()
    reads get_recent_turns(), and this message hasn't been logged yet at
    that point, so the current prompt never shows up twice (once inside
    "most recent turns", once as the live prompt itself)."""
    name = memory.maybe_extract_name(prompt)
    if name:
        memory.set_user_name(name)

    preference = memory.maybe_extract_preference(prompt)
    if preference:
        memory.add_preference(preference)


def _log_user_turn_and_condense(prompt: str, provider) -> None:
    """Log the user's half of the turn *after* the prefix has already been
    built from prior history, then run the rolling-summary maintenance
    pass. Used by all three ask_llm* entry points so they stay in sync."""
    memory.log_message("user", prompt)
    memory.maybe_condense_history(provider.ask)


def ask_llm(prompt: str) -> str:
    """
    Send one text prompt to the configured provider and return the reply text.

    Raises RuntimeError (never the raw SDK exception) with a human-readable
    message, so callers — the Phase 1 CLI or the Phase 2 GUI thread — can
    just catch RuntimeError and show it.

    Also handles personal memory: extracts a name/preference if the user
    just stated one, logs both sides of the turn, folds old history into
    the rolling summary as needed, and prepends whatever's known about the
    user to what's actually sent to the provider — none of which the
    provider itself knows is happening.
    """
    if not prompt or not prompt.strip():
        return "Say something and I'll respond."

    provider = get_provider(PROVIDER, api_key=API_KEY, model_name=MODEL_NAME)
    _extract_facts(prompt)

    full_prompt = memory.build_memory_prefix() + prompt
    _log_user_turn_and_condense(prompt, provider)
    reply = provider.ask(full_prompt)

    memory.log_message("assistant", reply)
    return reply


def ask_llm_stream(prompt: str):
    """
    Send one text prompt to the configured provider and yield reply text
    chunks as they arrive, instead of waiting for the full reply.

    Same RuntimeError contract as ask_llm: callers only ever need to catch
    RuntimeError, never a raw SDK exception. Same personal-memory handling
    as ask_llm, too — the full reply is accumulated as it streams out and
    logged once the stream ends.
    """
    if not prompt or not prompt.strip():
        yield "Say something and I'll respond."
        return

    provider = get_provider(PROVIDER, api_key=API_KEY, model_name=MODEL_NAME)
    _extract_facts(prompt)

    full_prompt = memory.build_memory_prefix() + prompt
    _log_user_turn_and_condense(prompt, provider)

    reply_chunks = []
    for chunk in provider.ask_stream(full_prompt):
        reply_chunks.append(chunk)
        yield chunk

    memory.log_message("assistant", "".join(reply_chunks))


def ask_llm_with_tools(
    prompt: str,
    on_tool_event: Optional[ToolEventCallback] = None,
    on_chunk: Optional[Callable[[str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> str:
    """
    Phase 4 — same shape and memory handling as ask_llm(), but gives the
    provider every registered tool (tools/registry.get_all_tools()) via its
    native function-calling mechanism, plus the tool-safety system prompt
    (tools/base.TOOL_SAFETY_SYSTEM_PROMPT — Security rule #1: tool results
    are data, never instructions).

    `on_tool_event`, if given, is forwarded straight to the provider and
    fires once per tool call/result/error as it happens — worker.py's
    ToolWorker wires this to a Qt signal so the UI's reasoning-trace panel
    can update live while the request is still in flight.

    `on_chunk` and `should_cancel` are forwarded straight to the provider
    too — see LLMProvider.ask_with_tools's docstring (providers/base.py) for
    exactly when on_chunk fires and what should_cancel does. worker.py wires
    on_chunk to a Qt signal so the UI can grow the reply bubble live instead
    of waiting for the whole answer, and should_cancel to a Stop button.

    Same RuntimeError contract as ask_llm: callers only ever need to catch
    RuntimeError, never a raw SDK exception.
    """
    if not prompt or not prompt.strip():
        return "Say something and I'll respond."

    provider = get_provider(PROVIDER, api_key=API_KEY, model_name=MODEL_NAME)
    _extract_facts(prompt)

    full_prompt = memory.build_memory_prefix() + prompt
    _log_user_turn_and_condense(prompt, provider)
    reply = provider.ask_with_tools(
        full_prompt,
        tools=get_all_tools(),
        system_instruction=TOOL_SAFETY_SYSTEM_PROMPT,
        on_tool_event=on_tool_event,
        on_chunk=on_chunk,
        should_cancel=should_cancel,
    )

    memory.log_message("assistant", reply)
    return reply
