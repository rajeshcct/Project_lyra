"""
Phase 14 -- browser tools: open_url and play_youtube.

open_url() hands the model's string straight to webbrowser.open(). That's
intentionally the "open literally any website" escape hatch
system_control_tool.py's module docstring warns against for subprocess
(there's no allowlist possible here -- the whole point is "any URL"), so
the one safety rail that *does* apply is restricting the scheme to
http(s)/no-scheme-assume-https before it's ever touched. That rules out
file://, javascript:, and any other handler being reached through this
tool, no matter what a prompt-injected page or search result tries to get
the model to pass in -- same "fixed safe arguments" spirit as
system_control_tool.py's app allowlist, just expressed as a scheme check
instead of a name lookup since the argument space here can't be a fixed
list.

play_youtube() reuses websearch_tool.py's `ddgs` dependency (already
installed, no API key, same free-tier-only principle as the rest of this
project) instead of the YouTube Data API. Results are filtered down to
only youtube.com/watch and youtu.be links before anything is opened, so a
search-result page for some unrelated site can't get opened under the
guise of "the video".
"""

import re
import webbrowser

from .base import ToolSpec
from .registry import register_tool

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


def open_url(url: str) -> str:
    """Open a website URL in the user's default browser."""
    url = (url or "").strip()
    if not url:
        raise RuntimeError("No URL given.")

    if not _SCHEME_RE.match(url):
        url = "https://" + url  # bare "google.com" -> "https://google.com"

    if not url.lower().startswith(("http://", "https://")):
        raise RuntimeError(
            f"'{url}' isn't a web address Lyra will open -- only http/https "
            "links are allowed."
        )

    try:
        opened = webbrowser.open(url)
    except Exception as e:
        raise RuntimeError(f"Could not open '{url}': {e}") from e
    if not opened:
        raise RuntimeError(f"Could not open '{url}' -- no browser was found to handle it.")
    return f"Opened {url}."


def play_youtube(query: str) -> str:
    """Search YouTube for `query` and open the first matching video."""
    query = (query or "").strip()
    if not query:
        raise RuntimeError("No search query given.")

    try:
        from ddgs import DDGS
    except ImportError as e:
        raise RuntimeError(
            "The 'ddgs' package isn't installed. Run 'pip install ddgs' "
            "(see requirements.txt) to enable YouTube search."
        ) from e

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(f"site:youtube.com/watch {query}", max_results=8))
    except Exception as e:
        raise RuntimeError(f"YouTube search failed for '{query}': {e}") from e

    video_url = next(
        (
            r.get("href", "")
            for r in results
            if "youtube.com/watch" in r.get("href", "") or "youtu.be/" in r.get("href", "")
        ),
        None,
    )
    if not video_url:
        raise RuntimeError(f"No YouTube video found for '{query}'.")

    try:
        webbrowser.open(video_url)
    except Exception as e:
        raise RuntimeError(f"Found a video for '{query}' but could not open it: {e}") from e
    return f"Playing '{query}' on YouTube: {video_url}"


register_tool(
    ToolSpec(
        name="open_url",
        description=(
            "Open a website URL in the user's default browser. Use when "
            "the user explicitly asks to open, visit, or go to a website "
            "(e.g. 'open google.com' or 'open stackoverflow.com'). Only "
            "http/https links can be opened. Do not use this for playing "
            "YouTube videos -- use play_youtube for that instead."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to open, e.g. 'stackoverflow.com' or 'https://google.com'.",
                }
            },
            "required": ["url"],
        },
        func=open_url,
    )
)

register_tool(
    ToolSpec(
        name="play_youtube",
        description=(
            "Search YouTube for `query` and open the first matching video "
            "so it plays in the browser. Use when the user asks to play or "
            "watch something 'on YouTube' (e.g. 'play Arijit Singh on "
            "YouTube'). For the user's own local music files, use "
            "play_music instead."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for on YouTube, e.g. 'Arijit Singh Tum Hi Ho'.",
                }
            },
            "required": ["query"],
        },
        func=play_youtube,
    )
)
