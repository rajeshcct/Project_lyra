# Lyra — Setup & Phases 1–3

Status: **Phase 1 (bare LLM chat), Phase 2 (PySide6 chat UI), and Phase 3
(voice + personal memory) done.**
Phase 4+ (tool-calling framework, real tools) not started yet.

---

## 1. Get a free Gemini API key

1. Go to https://aistudio.google.com/apikey
2. Sign in with a Google account, click "Create API key".
3. Copy the key (looks like `AIzaSy...`).

(You'll also want a free Groq key from https://console.groq.com/keys if
`LLM_PROVIDER=groq`, which is the default.)

## 2. One-time setup (run these in a terminal, inside this folder)

Open a terminal in `C:\Users\visha\Project_lyra` (in File Explorer: type
`cmd` in the address bar and hit Enter — that opens a terminal already
pointed here).

```bat
:: 1. Create the virtual environment
python -m venv venv

:: 2. Activate it (do this every time you open a new terminal for this project)
venv\Scripts\activate

:: 3. Install dependencies
pip install -r requirements.txt

:: 4. Create your real .env file from the template
copy .env.example .env
```

Now open `.env` in any text editor and fill in your real key(s). Save it.
`.env` is already in `.gitignore` — it will never get committed.

**If `pip install pyaudio` fails** (common on Windows — PyAudio has no
official wheel for every Python version): install a prebuilt wheel instead,
e.g. `pip install pipwin && pipwin install pyaudio`, or grab a `.whl` for
your exact Python version from
https://github.com/intxcc/pyaudio_portaudio/releases (or search
"unofficial PyAudio wheels windows") and `pip install <the .whl file>`.

**Check `python` and `pip` above actually point at Python 3.12** (`python
--version`). If your machine has multiple Python installs and the wrong one
gets picked up, use `py -3.12 -m venv venv` instead of `python -m venv venv`.

## 3. Run Phase 1 checkpoint (terminal only, no window)

```bat
venv\Scripts\activate
python test_llm.py
```

Type a message, press Enter, get a reply. Type `quit` to exit. This proves
the API key and the LLM call work before anything GUI-related is involved.

## 4. Run the app (Phase 2 UI + Phase 3 voice)

```bat
venv\Scripts\activate
python main.py
```

- Type in the box at the bottom, press Enter or click **Send** — the reply
  streams into the transcript above. The API call runs on a background
  thread (`lyra/worker.py`), so the window never freezes.
- Click the **🎤** button, speak, and it's transcribed straight into the
  input box and sent the same way typing does. Once the reply finishes, it
  is **spoken aloud** (only for that voice-triggered turn — typing never
  triggers speech). Mic capture (`lyra/stt.py`) and speech-to-text both run
  on their own background threads (`lyra/mic_worker.py`,
  `lyra/tts_worker.py`), same reasoning as the LLM call: nothing that can
  block runs on the UI thread.
- Typed text remains the permanent fallback the whole way through — voice
  is additive, never required.
- Tell it your name ("my name is ..." or "call me ...") and it's saved to
  `lyra_memory.db` (SQLite). Every later prompt in that run — and any
  future run — gets a short reminder of your name folded in before it's
  sent to the LLM, so it can address you by name without you repeating it.
  Every message either side sends is also logged to that same database's
  `chat_history` table, tagged with a per-run session id.

---

## Project structure

```
Project_lyra/
├── .env                       # your real key(s) (not committed)
├── .env.example               # template, safe to commit
├── .gitignore
├── requirements.txt
├── main.py                    # Phase 2/3: PySide6 window, entry point
├── lyra_memory.db              # Phase 3: SQLite db (users, chat_history) — gitignored, created on first run
├── assets/
│   └── splash.png              # your own startup splash image (see below)
└── lyra/                      # the actual application package
    ├── __init__.py
    ├── config.py                # picks provider + model from .env (LLM_PROVIDER)
    ├── llm_client.py             # Phase 1: ask_llm / ask_llm_stream, no GUI dependency
    ├── worker.py                  # Phase 2: QThread wrapper around ask_llm_stream
    ├── stt.py                      # Phase 3: listen_once() — mic capture + speech recognition
    ├── tts.py                       # Phase 3: speak() — OS text-to-speech via pyttsx3
    ├── mic_worker.py                 # Phase 3: QThread wrapper around stt.listen_once
    ├── tts_worker.py                  # Phase 3: QThread wrapper around tts.speak
    ├── memory.py                       # Phase 3: SQLite users/chat_history + name-extraction + memory prefix
    ├── providers/                # one file per LLM backend, common interface
    │   ├── __init__.py            # auto-discovers & registers provider modules
    │   ├── base.py                 # LLMProvider abstract base class
    │   ├── registry.py              # name -> class lookup used by get_provider()
    │   ├── groq_provider.py          # GroqProvider(LLMProvider)
    │   └── gemini_provider.py        # GeminiProvider(LLMProvider)
    └── ui/                        # visual concerns, one file each
        ├── theme.py                # color palette + stylesheet (QSS), one accent color
        ├── splash.py                # startup splash screen: fades in assets/splash.png
        ├── hud_background.py         # animated HUD background (QPainter, no image needed)
        └── chat_bubble.py             # per-message bubble widget (rounded, role-colored)
```

`llm_client.py` has zero PySide6 import and zero provider-SDK import — it's
reused unchanged by the GUI and never needs to change when a provider is
added. Same idea for `stt.py` / `tts.py`: no PySide6 import, so they could
be reused from a CLI just like `llm_client.py` is in `test_llm.py`.

Adding a new LLM backend (e.g. OpenAI) is a self-contained step:

1. Create `lyra/providers/openai_provider.py`, subclass `LLMProvider`,
   implement `ask()` and `ask_stream()`, decorate the class with
   `@register_provider("openai")`.
2. Add an `"openai": {...}` entry to `PROVIDERS` in `lyra/config.py`.
3. Set `LLM_PROVIDER=openai` in `.env`.

No existing file — `llm_client.py`, `worker.py`, `main.py` — needs to be
touched. This matters from Phase 4 onward: when the tool-calling framework
goes in, it extends this same structure rather than replacing it.

## One-time step: add your splash image

The UI theme (cyan-blue HUD look, animated background, startup splash) is
already wired up in `lyra/ui/theme.py` / `hud_background.py` / `splash.py`
— nothing to install, no new dependencies. The only manual step is
dropping an image in place, since Claude can write code to your machine
but can't transfer image bytes onto it directly:

1. Save whatever image you want as the startup splash — right-click it,
   "Save image as…"
2. Save it as exactly: `Project_lyra\assets\splash.png`

That's it — `python main.py` will fade it in on startup automatically. If
`assets/splash.png` isn't there, the app still starts fine; it just shows a
plain dark splash instead of erroring out.

## Notes / deviations from the original plan doc

- Using **`google-genai`** (the current, actively maintained SDK) instead of
  `google-generativeai`, which Google fully deprecated (EOL Nov 30, 2025).
  Only the import and client-construction lines differ — the rest of the
  plan's phases apply unchanged.
- Speech-to-text uses SpeechRecognition's built-in `recognize_google()` —
  free, no API key, consistent with the rest of the project running on
  free-tier services. It does need internet access for that recognition
  call (same as the LLM calls already do).
- A reply is only spoken aloud if the turn that produced it was
  voice-triggered. Typing a message never triggers unsolicited speech.
- Personal memory (`lyra/memory.py`) only recognizes two explicit
  self-introduction phrases ("my name is ...", "call me ...") — deliberately
  conservative so casual sentences like "I'm fine" never get misread as a
  name. Phase 5's "personal memory refinement" is where this is meant to
  get smarter (preferences, the rolling-summary context pattern).
- `users` is a single row (id=1) — this is a single-user desktop app, not
  multi-account. `chat_history` is tagged with a `session_id` generated
  once per process run, ready for Phase 5's sliding-window + summary logic
  to key off later.
- Git repo isn't initialized yet — say the word if you want that done too
  (`git init`, first commit, etc.).

## Security note

`.env.example` previously had a real Groq key pasted into it instead of a
placeholder. Since that file is meant to be committed, treat that key as
compromised — rotate it at https://console.groq.com/keys and put only
`your_groq_api_key_here`-style placeholders in `.env.example` going
forward. Real keys belong in `.env` only, which stays out of git.

## What's next (Phase 4)

Tool-calling framework wired to Gemini's native function calling (a dummy
calculator tool first, to prove the loop), plus the reasoning-trace panel
in the UI. See the plan doc's Security Considerations section — three
rules (tool results are data not instructions, no raw `run_command`, human-
triggered confirmation for sensitive actions) need to be built into the
framework from day one, not patched in later.
