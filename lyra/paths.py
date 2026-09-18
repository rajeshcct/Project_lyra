"""
Phase 13 — packaging-safe path resolution.
--------------------------------------------
Every earlier module that needed "the project root" computed it locally
as `Path(__file__).resolve().parent...`. That's correct when running from
source, but breaks under a PyInstaller --onefile build: at runtime, a
frozen module's __file__ resolves inside PyInstaller's onefile temp
extraction directory (sys._MEIPASS), which PyInstaller deletes the moment
the .exe process exits. Any code that wrote lyra_memory.db, rag_store/,
assets/screenshots/, credentials.json, or token.json relative to
__file__ would silently write them into that temp folder -- working fine
run-from-source, but resetting every reminder/chat/document/login on
every single launch of the packaged .exe, and needing a fresh Gmail OAuth
browser flow every time too.

Two roots, because bundled read-only assets and real user data need to
resolve differently once frozen:

  DATA_ROOT   -- where persistent, writable app data lives (the sqlite
                 db, rag_store/, assets/screenshots/, credentials.json,
                 token.json, .env). Always the folder the .exe itself
                 sits in when frozen, so it survives across runs exactly
                 like it does next to main.py when run from source.

  BUNDLE_ROOT -- where read-only assets PyInstaller bundled INTO the exe
                 live at runtime (splash.png, icons, etc.). PyInstaller
                 extracts these to sys._MEIPASS (onefile) at startup;
                 that's fine to read from since it exists for the
                 lifetime of that run, it just can't be written to.

PROJECT_ROOT is kept as an alias to DATA_ROOT for existing call sites
that just want "the project folder" for writable data -- the safer
default when a module doesn't care about the bundled/writable
distinction.
"""

import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    # sys.executable is the .exe's own path when frozen -- its parent
    # folder is where the user keeps the .exe, and where all of this
    # app's data files should live alongside it (same layout as running
    # main.py from the project folder does).
    DATA_ROOT = Path(sys.executable).resolve().parent
    # sys._MEIPASS only exists when frozen -- PyInstaller's per-run
    # extraction dir for bundled read-only data (onefile) or the
    # "_internal" folder next to the exe (onedir).
    BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", DATA_ROOT))
else:
    # Running from source: this file lives at <project_root>/lyra/paths.py
    DATA_ROOT = Path(__file__).resolve().parent.parent
    BUNDLE_ROOT = DATA_ROOT

PROJECT_ROOT = DATA_ROOT
