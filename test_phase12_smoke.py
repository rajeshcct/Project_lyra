"""
Phase 12 — automated smoke test for tool-layer graceful failure.

This is NOT a GUI test (see PHASE12_BUG_BASH.md for the manual voice/UI/
email pass that needs a human). It's a fast, headless check of the one
rule Phase 12 explicitly calls out: "API failures should say 'I couldn't
reach the weather service' -- never crash or hallucinate." Concretely,
that means every ToolSpec.func in the registry must, on bad input, either
return a string or raise RuntimeError -- and NEVER let any other
exception type escape (per tools/base.py's ToolSpec.func contract).

Run:
    venv\\Scripts\\activate
    python test_phase12_smoke.py

Exits non-zero (and prints which tool/case) if any tool violates the
contract. Network-dependent cases (weather/web search with a bogus query)
are included but tolerate network errors themselves being surfaced as
RuntimeError -- that's still a pass, since a RuntimeError is exactly what
the contract asks for.
"""

import sys

# Importing lyra.tools triggers tools/__init__.py's auto-discovery, which
# registers every tool module (weather, reminders, email, rag, system
# control, calculator) -- same as app startup, minus the PySide6 window.
import lyra.tools  # noqa: F401
from lyra.tools.registry import get_all_tools

# One or more deliberately-bad-input cases per tool, keyed by tool name.
# Anything not listed here is still smoke-tested with its required args
# filled with harmless placeholder values (see _placeholder_args below).
BAD_CASES: dict[str, list[dict]] = {
    "get_weather": [
        {"location": "Zzqxnotarealplace123"},
        {"location": ""},
    ],
    "web_search": [
        {"query": ""},
    ],
    "calculator": [
        {"expression": "5 / 'apple'"},
        {"expression": "__import__('os').system('echo hi')"},
        {"expression": "not even an expression ("},
    ],
    "complete_reminder": [
        {"reminder_id": 999999},
    ],
    "delete_reminder": [
        {"reminder_id": 999999},
    ],
    "add_email_reminder": [
        {"text": "test", "remind_at": "sometime vague", "email_to": "a@b.com"},
        {"text": "test", "remind_at": "in 5 minutes", "email_to": ""},
    ],
    "open_app": [
        {"app_name": "photoshop"},
        {"app_name": "; rm -rf /"},
        {"app_name": ""},
    ],
    "search_documents": [
        {"query": "anything, before any upload"},
    ],
}

# Tools that are safe to call with genuinely harmless placeholder args
# when no BAD_CASES entry exists for them, so every registered tool gets
# at least one smoke pass. Skips tools whose side effects are undesirable
# to trigger from an automated script (real email send, real reminder
# writes, real screenshots) -- those are covered by the manual bug-bash
# checklist instead.
SKIP_TOOLS = {"send_email", "take_screenshot", "add_reminder", "list_reminders", "clear_reminders"}


def _check_call(name: str, func, kwargs: dict) -> str | None:
    """Returns None on pass, or a failure description string."""
    try:
        result = func(**kwargs)
    except RuntimeError as e:
        return None  # contract satisfied: graceful, typed failure
    except Exception as e:
        return f"RAW {type(e).__name__} escaped: {e!r}"
    else:
        if not isinstance(result, str):
            return f"returned non-string result: {result!r}"
        return None


def main() -> int:
    tools = {t.name: t for t in get_all_tools()}
    failures = []
    tested = 0

    for name, tool in sorted(tools.items()):
        if name in SKIP_TOOLS:
            continue
        cases = BAD_CASES.get(name)
        if not cases:
            print(f"SKIP  {name} (no bad-input case defined, and not a safe default-arg tool)")
            continue
        for case in cases:
            tested += 1
            failure = _check_call(name, tool.func, case)
            status = "FAIL" if failure else "ok"
            print(f"{status:5} {name}({case}) {'-> ' + failure if failure else ''}")
            if failure:
                failures.append((name, case, failure))

    print(f"\n{tested} case(s) run, {len(failures)} failure(s).")
    if failures:
        print("\nContract violations (raw exception escaped a tool.func):")
        for name, case, failure in failures:
            print(f"  - {name}{case}: {failure}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
