# Phase 13 — Packaging (PyInstaller)

Builds Lyra into a standalone `Lyra.exe` that runs without a Python
install. Optional per the plan, but the checkpoint is strict: **the .exe
must run identically to `python main.py`**, including surviving a
restart with all data intact.

## 1. Install the build dependency

```
venv\Scripts\activate
pip install -r requirements.txt
```

(`pyinstaller` was added to `requirements.txt` for this phase.)

## 2. Build

```
pyinstaller lyra.spec
```

Do **not** run the bare `pyinstaller main.py --onefile --windowed`
instead — see `lyra.spec`'s docstring for why (chromadb /
sentence-transformers / googleapiclient need explicit `collect_all()`
handling the plain CLI flags don't do).

Output: `dist\Lyra.exe`.

## 3. Place the data files next to the .exe

These are gitignored on purpose and never bundled into the binary (per
the plan's Credential handling rule — no hardcoded keys in the .exe).
Copy them manually into `dist\` so they sit next to `Lyra.exe`:

- `.env` (with your real `GROQ_API_KEY`/`GEMINI_API_KEY`)
- `credentials.json` (if you use the Gmail tool)

`lyra/paths.py` resolves all persistent data (the SQLite db, `rag_store/`,
`assets/screenshots/`, `token.json`) relative to wherever `Lyra.exe`
itself lives — so as long as you always launch it from `dist\`, everything
behaves exactly like running from source.

## 4. Verify — this is the actual Phase 13 checkpoint

Don't just confirm it launches. Check each of these explicitly:

- [ ] Double-click `dist\Lyra.exe` — window opens, splash shows, chat works.
- [ ] **Mic test, separately from the source-run version.** PyAudio/
      PortAudio bundling is the most common PyInstaller+audio failure —
      test hands-free voice in the built .exe even if you already tested
      it running from source. If the mic works from source but fails
      only in the .exe, rebuild after adding
      `--collect-binaries pyaudio` (or bundle the PortAudio DLL
      explicitly) rather than assuming it's a code bug.
- [ ] Add a reminder, send a chat message, upload a document.
- [ ] **Close the .exe completely, reopen it, and confirm all three are
      still there** (this is what the `lyra/paths.py` fix in this
      session made possible — without it, everything above would've
      reset on every launch).
- [ ] Send/receive a Gmail email once — confirms `token.json` also
      persists next to the .exe rather than re-prompting OAuth login
      every launch.
- [ ] Confirm no API key is visible in plain text if you run
      `findstr /s "your_actual_key_here" dist\Lyra.exe` — should find
      nothing, since keys load from `.env` at runtime, never compiled in.

## Troubleshooting

- **Startup is slow (several seconds before the window appears):**
  normal for `--onefile` — chromadb/sentence-transformers are large and
  get re-extracted to a temp dir on every launch. If it's too slow for
  your demo, switch `lyra.spec` to `--onedir` mode instead (produces a
  `dist\Lyra\` folder instead of a single file — ship the whole folder).
- **RAG or Gmail features crash only in the .exe, not from source:** you
  probably built with the bare CLI flags instead of `lyra.spec` — rebuild
  with `pyinstaller lyra.spec`.
- **Antivirus flags the .exe:** common false-positive for PyInstaller
  onefile builds (the self-extracting bootloader pattern looks similar to
  some malware droppers). Not a code issue; whitelisting the file or
  switching to `--onedir` usually resolves it for a demo machine.
