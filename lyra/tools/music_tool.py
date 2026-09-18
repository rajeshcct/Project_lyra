"""
Phase 14 -- local music tools: play_music and list_music.

Folder location comes from MUSIC_DIR in .env (see .env.example), same
"config lives in .env, not hardcoded" pattern as config.py's provider
keys. load_dotenv() is called again here (harmless if already loaded by
config.py -- python-dotenv doesn't override already-set environment
variables by default) with the same explicit PROJECT_ROOT / ".env" path
paths.py's own docstring calls for, so this module works standalone even
if it's ever imported before lyra.config is.

play_music() only ever resolves a filename that already exists inside
MUSIC_DIR -- song_name is used purely to pick which file from that
directory listing to play (fuzzy match), never interpolated into a raw
path, so a model-supplied string like "../../something" can't escape the
music folder (Path.name / the directory scan below never leaves it).
Playback itself goes through os.startfile(), same as the rest of this
Windows-only app (system_control_tool.py's `cmd /c start`), which just
asks the OS to open the file with whatever the user's own default music
player is -- no new subprocess allowlist needed since we're never
choosing *which* program runs, only *which file* it opens.
"""

import difflib
import os
import random
from pathlib import Path

from dotenv import load_dotenv

from ..paths import PROJECT_ROOT
from .base import ToolSpec
from .registry import register_tool

load_dotenv(PROJECT_ROOT / ".env")

_MUSIC_EXTENSIONS = (".mp3", ".wav", ".flac")


def _music_dir() -> Path:
    raw = os.environ.get("MUSIC_DIR", "").strip()
    if not raw:
        raise RuntimeError(
            "MUSIC_DIR isn't set. Add a line like "
            "MUSIC_DIR=C:\\Users\\you\\Music to your .env file."
        )
    music_dir = Path(raw)
    if not music_dir.is_dir():
        raise RuntimeError(f"MUSIC_DIR '{music_dir}' doesn't exist or isn't a folder.")
    return music_dir


def _list_song_files() -> list[Path]:
    music_dir = _music_dir()
    return sorted(
        p for p in music_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _MUSIC_EXTENSIONS
    )


def _fuzzy_match(song_name: str, songs: list[Path]) -> Path | None:
    """Exact stem match first, then substring, then difflib's closest
    ratio match -- so 'tum hi ho' matches 'Tum_Hi_Ho_Arijit_Singh.mp3'
    without the user needing the exact filename."""
    needle = song_name.strip().lower()
    for p in songs:
        if needle == p.stem.lower():
            return p
    for p in songs:
        if needle in p.stem.lower():
            return p
    stems = [p.stem.lower() for p in songs]
    close = difflib.get_close_matches(needle, stems, n=1, cutoff=0.4)
    if close:
        return songs[stems.index(close[0])]
    return None


def list_music() -> str:
    """List the song files available in the configured music folder."""
    songs = _list_song_files()
    if not songs:
        return "No songs found in the music folder."
    names = [p.stem for p in songs]
    return f"Available songs ({len(names)}): " + ", ".join(names)


def play_music(song_name: str = "") -> str:
    """Play a random song, or the closest fuzzy match to `song_name`."""
    songs = _list_song_files()
    if not songs:
        raise RuntimeError("No songs found in the music folder.")

    song_name = (song_name or "").strip()
    if not song_name:
        chosen = random.choice(songs)
    else:
        chosen = _fuzzy_match(song_name, songs)
        if chosen is None:
            raise RuntimeError(
                f"No song matching '{song_name}' was found. Ask list_music "
                "for what's available."
            )

    try:
        import subprocess
        # SW_SHOWMINIMIZED = 7 -- opens the player minimized in the taskbar
        # so it plays in the background without stealing focus from Lyra.
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 7  # SW_SHOWMINIMIZED
        subprocess.Popen(
            ["cmd", "/c", "start", "/min", "", str(chosen)],
            startupinfo=si,
        )
    except Exception as e:
        raise RuntimeError(f"Could not play '{chosen.name}': {e}") from e
    return f"Playing '{chosen.stem}'."


register_tool(
    ToolSpec(
        name="play_music",
        description=(
            "Play a song from the user's own local music folder with "
            "their default music player. Omit `song_name` (or leave it "
            "empty) to play a random song; otherwise the closest matching "
            "filename is played (fuzzy match, so 'Tum Hi Ho' finds "
            "'Tum_Hi_Ho_Arijit_Singh.mp3'). Use this for the user's own "
            "music library -- not for YouTube or streaming, which have "
            "their own tools (play_youtube)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "song_name": {
                    "type": "string",
                    "description": "Song to play, e.g. 'Tum Hi Ho'. Leave empty for a random song.",
                }
            },
            "required": [],
        },
        func=play_music,
    )
)

register_tool(
    ToolSpec(
        name="list_music",
        description=(
            "List the song files available in the user's local music "
            "folder. Use this when the user asks what songs are available, "
            "or to find the exact name of a song before calling "
            "play_music. Takes no arguments."
        ),
        parameters={"type": "object", "properties": {}},
        func=list_music,
    )
)
