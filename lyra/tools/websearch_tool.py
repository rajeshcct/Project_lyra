"""
Phase 5 — web search tool.

Uses the `ddgs` package (DuckDuckGo search) — free, no API key, no
signup, same "runs on free-tier services" principle as the rest of this
project (Groq/Gemini free tiers, Open-Meteo, SpeechRecognition's free
recognize_google()). The SDK import is deliberately lazy (inside the
function, not at module top) — same pattern groq_provider.py /
gemini_provider.py use for their own SDKs — so a missing/not-yet-installed
package only breaks this one tool call with a clear message, instead of
crashing app startup for every tool.
"""

from .base import ToolSpec
from .registry import register_tool

_MAX_RESULTS = 5


def web_search(query: str) -> str:
    """Run a web search for `query` and return a short list of results."""
    try:
        from ddgs import DDGS
    except ImportError as e:
        raise RuntimeError(
            "The 'ddgs' package isn't installed. Run "
            "'pip install ddgs' (see requirements.txt) to enable web search."
        ) from e

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=_MAX_RESULTS))
    except Exception as e:
        raise RuntimeError(f"Web search failed for '{query}': {e}") from e

    if not results:
        return f"No web results found for '{query}'."

    lines = []
    for i, r in enumerate(results, start=1):
        title = r.get("title", "(no title)")
        url = r.get("href", "")
        snippet = r.get("body", "").strip()
        lines.append(f"{i}. {title} — {snippet} ({url})")
    return "\n".join(lines)


register_tool(
    ToolSpec(
        name="web_search",
        description=(
            "Search the web and return a short list of results (title, "
            "snippet, URL) for a query. Use this for current events, facts "
            "you're unsure of, or anything that might have changed since "
            "your training — never guess when you can look it up."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                }
            },
            "required": ["query"],
        },
        func=web_search,
    )
)
