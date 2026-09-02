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

from typing import Optional

from .config import PROVIDER, MODEL_NAME, API_KEY
from .providers import get_provider
from .providers.base import ToolEventCallback
from .tools import get_all_tools, TOOL_SAFETY_SYSTEM_PROMPT
from . import memory


def ask_llm(prompt: str) -> str:
    """
    Send one text prompt to the configured provider and return the reply text.

    Raises RuntimeError (never the raw SDK exception) with a human-readable
    message, so callers — the Phase 1 CLI or the Phase 2 GUI thread — can
    just catch RuntimeError and show it.

    Also handles Phase 3's personal memory: extracts a name if the user just
    introduced themselves, logs both sides of the turn to chat_history, and
    prepends whatever's known about the user to what's actually sent to the
    provider — none of which the provider itself knows is happening.
    """
    if not prompt or not prompt.strip():
        return "Say something and I'll respond."

    name = memory.maybe_extract_name(prompt)
    if name:
        memory.set_user_name(name)
    memory.log_message("user", prompt)

    provider = get_provider(PROVIDER, api_key=API_KEY, model_name=MODEL_NAME)
    full_prompt = memory.build_memory_prefix() + prompt
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

    name = memory.maybe_extract_name(prompt)
    if name:
        memory.set_user_name(name)
    memory.log_message("user", prompt)

    provider = get_provider(PROVIDER, api_key=API_KEY, model_name=MODEL_NAME)
    full_prompt = memory.build_memory_prefix() + prompt

    reply_chunks = []
    for chunk in provider.ask_stream(full_prompt):
        reply_chunks.append(chunk)
        yield chunk

    memory.log_message("assistant", "".join(reply_chunks))


def ask_llm_with_tools(
    prompt: str, on_tool_event: Optional[ToolEventCallback] = None
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

    Same RuntimeError contract as ask_llm: callers only ever need to catch
    RuntimeError, never a raw SDK exception.
    """
    if not prompt or not prompt.strip():
        return "Say something and I'll respond."

    name = memory.maybe_extract_name(prompt)
    if name:
        memory.set_user_name(name)
    memory.log_message("user", prompt)

    provider = get_provider(PROVIDER, api_key=API_KEY, model_name=MODEL_NAME)
    full_prompt = memory.build_memory_prefix() + prompt
    reply = provider.ask_with_tools(
        full_prompt,
        tools=get_all_tools(),
        system_instruction=TOOL_SAFETY_SYSTEM_PROMPT,
        on_tool_event=on_tool_event,
    )

    memory.log_message("assistant", reply)
    return reply
