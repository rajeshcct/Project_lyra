# Lyra — Setup & Phase 1/2

Status: **Phase 1 (bare LLM chat) and Phase 2 (minimal PySide6 chat UI) done.**
Phase 3+ (voice, tools, memory, etc.) not started yet.

---

## 1. Get a free Gemini API key

1. Go to https://aistudio.google.com/apikey
2. Sign in with a Google account, click "Create API key".
3. Copy the key (looks like `AIzaSy...`).

## 2. One-time setup (run these in a terminal, inside this folder)

Open a terminal in `C:\Users\rajes\Downloads\Project_lyra` (in File Explorer:
type `cmd` in the address bar and hit Enter — that opens a terminal already
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

Now open `.env` in any text editor and replace `your_api_key_here` with the
real key from step 1. Save it. `.env` is already in `.gitignore` — it will
never get committed.

**Check `python` and `pip` above actually point at Python 3.12** (`python
--version`). If your machine has multiple Python installs and the wrong one
gets picked up, use `py -3.12 -m venv venv` instead of `python -m venv venv`.

## 3. Run Phase 1 checkpoint (terminal only, no window)

```bat
venv\Scripts\activate
python test_llm.py
```

Type a message, press Enter, get a reply. Type `quit` to exit. This proves
the API key and the Gemini call work before anything GUI-related is involved.

## 4. Run Phase 2 (the actual chat window)

```bat
venv\Scripts\activate
python main.py
```

Type in the box at the bottom, press Enter or click Send. The reply streams
into the transcript above. The window stays responsive while waiting on
Gemini — the API call runs on a background thread (`worker.py`), never on
the UI thread.

---

## Project structure

```
Project_lyra/
├── .env                     # your real key (not committed)
├── .env.example             # template, safe to commit
├── .gitignore
├── requirements.txt
├── config.py                # picks provider + model from .env (LLM_PROVIDER)
├── providers/                # one file per LLM backend, common interface
│   ├── __init__.py            # auto-discovers & registers provider modules
│   ├── base.py                 # LLMProvider abstract base class
│   ├── registry.py              # name -> class lookup used by get_provider()
│   ├── groq_provider.py          # GroqProvider(LLMProvider)
│   └── gemini_provider.py        # GeminiProvider(LLMProvider)
├── llm_client.py             # Phase 1: ask_llm(prompt) -> str, no GUI dependency
├── test_llm.py                # Phase 1 checkpoint: CLI loop
├── assets/
│   └── splash.png                # your own startup splash image (see below)
├── theme.py                     # color palette + stylesheet (QSS), one accent color
├── splash.py                     # startup splash screen: fades in assets/splash.png
├── hud_background.py             # animated HUD background (QPainter, no image needed)
├── worker.py                       # Phase 2: QThread wrapper around ask_llm
└── main.py                          # Phase 2: PySide6 window, entry point
```

`llm_client.py` has zero PySide6 import and zero provider-SDK import — it's
reused unchanged by the GUI and never needs to change when a provider is
added. Adding a new LLM backend (e.g. OpenAI) is a self-contained step:

1. Create `providers/openai_provider.py`, subclass `LLMProvider`, implement
   `ask()`, decorate the class with `@register_provider("openai")`.
2. Add an `"openai": {...}` entry to `PROVIDERS` in `config.py`.
3. Set `LLM_PROVIDER=openai` in `.env`.

No existing file — `llm_client.py`, `worker.py`, `main.py` — needs to be
touched. This matters from Phase 4 onward: when the tool-calling framework
goes in, it extends this same structure rather than replacing it.

## One-time step: add your splash image

The UI theme (cyan-blue HUD look, animated background, startup splash) is
already wired up in `theme.py` / `hud_background.py` / `splash.py` —
nothing to install, no new dependencies. The only manual step is dropping
an image in place, since Claude can write code to your machine but can't
transfer image bytes onto it directly:

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
- `requirements.txt` only has what Phase 1/2 actually use (`PySide6`,
  `google-genai`, `python-dotenv`). `SpeechRecognition`, `PyAudio`,
  `pyttsx3` etc. get added in Phase 3 — no point installing PyAudio (the
  most failure-prone install on Windows) before you need it.
- Git repo isn't initialized yet — say the word if you want that done too
  (`git init`, first commit, etc.).

## What's next (Phase 3)

Mic input (`SpeechRecognition` + PyAudio) → feeds into the same
`ask_gemini()` → `pyttsx3` speaks the reply. Text input in `main.py` stays
as the permanent fallback — that's a rule for the whole project, not just
this phase.
