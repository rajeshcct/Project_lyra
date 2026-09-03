# Lyra — Setup & Phases 1–6

Status: **Phase 1 (bare LLM chat), Phase 2 (PySide6 chat UI), Phase 3
(voice + personal memory), Phase 4 (tool-calling framework +
reasoning-trace panel), Phase 5 (real tools + personal-memory
refinement), and Phase 6 (multi-step tool chains) done.**
Phase 7+ (further phases from the plan) not started yet.

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

## 4. Run the app (Phase 2 UI + Phase 3 voice + Phase 4 tools)

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
- Ask it a calculation ("what's 47 * 89?") and it calls the built-in
  `calculator` tool instead of guessing the answer itself. A **reasoning
  trace panel** appears above the input box while the request is in
  flight, showing the tool being called and its result live, before the
  final answer is added to the transcript as a normal reply. Every turn
  goes through this tool-enabled path now, so ordinary questions still
  work exactly as before — the model just doesn't happen to call a tool
  for those, and the panel stays hidden.

---

## Project structure

```
Project_lyra/
├── .env                       # your real key(s) (not committed)
├── .env.example               # template, safe to commit
├── .gitignore
├── requirements.txt
├── main.py                    # Phase 2/3/4: PySide6 window, entry point
├── lyra_memory.db              # Phase 3/5: SQLite db (users, chat_history, reminders) — gitignored, created on first run
├── assets/
│   └── splash.png              # your own startup splash image (see below)
└── lyra/                      # the actual application package
    ├── __init__.py
    ├── config.py                # picks provider + model from .env (LLM_PROVIDER)
    ├── llm_client.py             # Phase 1/4: ask_llm / ask_llm_stream / ask_llm_with_tools
    ├── worker.py                  # Phase 2/4: QThread wrappers (LLMWorker, ToolWorker)
    ├── stt.py                      # Phase 3: listen_once() — mic capture + speech recognition
    ├── tts.py                       # Phase 3: speak() — OS text-to-speech via pyttsx3
    ├── mic_worker.py                 # Phase 3: QThread wrapper around stt.listen_once
    ├── tts_worker.py                  # Phase 3: QThread wrapper around tts.speak
    ├── memory.py                       # Phase 3/5: SQLite users/chat_history + name/preference extraction + rolling-summary context prefix
    ├── reminders.py                     # Phase 5: SQLite reminders list (add/list/complete) backing reminder_tool.py
    ├── providers/                # one file per LLM backend, common interface
    │   ├── __init__.py            # auto-discovers & registers provider modules
    │   ├── base.py                 # LLMProvider abstract base class (ask/ask_stream/ask_with_tools)
    │   ├── registry.py              # name -> class lookup used by get_provider()
    │   ├── groq_provider.py          # GroqProvider(LLMProvider) — OpenAI-style tool calling
    │   └── gemini_provider.py        # GeminiProvider(LLMProvider) — native function calling
    ├── tools/                    # Phase 4: tool-calling framework, one file per tool
    │   ├── __init__.py            # auto-discovers & registers tool modules
    │   ├── base.py                 # ToolSpec dataclass + TOOL_SAFETY_SYSTEM_PROMPT
    │   ├── registry.py              # name -> ToolSpec lookup used by ask_with_tools()
    │   ├── calculator_tool.py        # dummy tool that proves the loop end-to-end
    │   ├── weather_tool.py            # Phase 5: current conditions via Open-Meteo (no API key)
    │   ├── websearch_tool.py          # Phase 5: web search via the `ddgs` package (no API key)
    │   └── reminder_tool.py           # Phase 5: add_reminder/list_reminders/complete_reminder over reminders.py
    └── ui/                        # visual concerns, one file each
        ├── theme.py                # color palette + stylesheet (QSS), one accent color
        ├── splash.py                # startup splash screen: fades in assets/splash.png
        ├── hud_background.py         # static HUD grid background (QPainter, no animation — see Notes)
        ├── chat_bubble.py             # per-message bubble widget (rounded, role-colored)
        └── trace_panel.py             # Phase 4: live tool-call/result log above the input box
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
- `hud_background.py` originally animated a sweeping scanline via a
  ~30fps `QTimer`, repainting the whole window continuously even when
  totally idle. That constant background CPU draw turned out to be the
  main source of the app feeling heavy, so the timer and the scanline are
  gone — the HUD grid is now rendered once into a cached pixmap and just
  sits there. Same visual language, no per-frame cost.
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

## Phase 4 notes

Tool-calling is wired to both providers' native function-calling
mechanisms (Gemini's `FunctionDeclaration`/manual execution, Groq's
OpenAI-style `tools`/`tool_choice`), proven end-to-end with a dummy
`calculator` tool. All three of the plan's Security Considerations rules
are built into the framework itself, not left for a later phase to retrofit:

1. **Tool results are data, not instructions** — `tools/base.py`'s
   `TOOL_SAFETY_SYSTEM_PROMPT` is sent as an actual system-level
   instruction on every tool-enabled call.
2. **No raw `run_command`** — `calculator_tool.py` evaluates via a
   restricted AST walk, not `eval()`; every future tool is expected to
   follow the same "fixed function, fixed safe arguments" shape.
3. **Human-triggered confirmation for sensitive actions** —
   `ToolSpec.requires_confirmation` exists now (default `False`); both
   providers refuse to auto-run a tool with it set to `True` rather than
   executing it silently. No Phase 4 tool sets it yet — an actual
   confirmation dialog is Phase 5+ work, once there's a tool that needs one.

Tool calls/results show up live in the UI via the reasoning-trace panel
(`lyra/ui/trace_panel.py`), driven by `ToolWorker`'s `tool_event` signal
(`worker.py`). Every chat turn now goes through the tool-enabled path
(`ask_llm_with_tools`); replies no longer stream token-by-token the way
Phase 2/3's did, since the model has to finish deciding whether to call a
tool before any final answer text exists.

## Phase 5 notes

Two independent pieces, per the plan:

**Real tools beyond the dummy calculator** — three new self-contained
modules dropped into `tools/` (nothing else needed to change, per
`tools/__init__.py`'s auto-discovery):

- `weather_tool.py` — `get_weather(location, unit)` via Open-Meteo
  (geocoding + forecast), free and keyless.
- `websearch_tool.py` — `web_search(query)` via the `ddgs` package
  (DuckDuckGo search), also free and keyless.
- `reminder_tool.py` — `add_reminder` / `list_reminders` /
  `complete_reminder`, backed by a new `reminders` table in
  `lyra_memory.db` (`lyra/reminders.py`). This is a persisted list, not an
  alarm clock: Lyra isn't always running, so there's no background
  scheduler or OS notification when a reminder's time arrives — it's
  surfaced back to the user only when they ask what's on their list.

Both weather and web search import their third-party dependency
(`requests`, `ddgs`) lazily inside the function rather than at module
top, same reasoning as the provider modules lazily importing their own
SDKs: `tools/__init__.py` imports every tool module at app startup, so a
top-level import would mean a missing dependency crashes the whole app
instead of just that one tool call.

**Personal-memory refinement** (`lyra/memory.py`), on top of Phase 3's
name-only memory:

- **Preferences** — `maybe_extract_preference()` catches explicit
  "I like/love/prefer/hate/dislike ..." and "my favorite X is Y"
  statements (same conservative, low-false-positive spirit as the
  existing name extractor — casual chat never becomes a stored
  preference) and appends them to a capped, de-duplicated list in
  `users.preferences`.
- **Rolling-summary context pattern** — Phase 3 sent the model *zero*
  conversation history (only the name line), so every turn was
  effectively stateless beyond that. Phase 5 adds:
  - `get_recent_turns()` — the last `RECENT_TURNS_KEPT` (8) messages,
    sent to the model verbatim every turn.
  - `maybe_condense_history()` — once more than
    `RECENT_TURNS_KEPT + SUMMARY_BATCH_SIZE` messages have piled up, the
    oldest `SUMMARY_BATCH_SIZE` (10) are folded into a running summary via
    one extra LLM call (using whichever provider is already configured —
    `memory.py` takes the summarizing call in as a plain function rather
    than importing `providers/` itself, keeping it provider-agnostic),
    then marked `summarized` so they're excluded from future context and
    never re-summarized. A failed summarization call just gets retried
    next turn — it never loses data.
  - `build_memory_prefix()` now folds name + preferences + summary +
    recent turns into one background-context preamble, same
    "framed as context, not a live instruction" approach as Phase 3.

Everything above is exercised from all three `llm_client.py` entry points
(`ask_llm`, `ask_llm_stream`, `ask_llm_with_tools`) via two small shared
helpers, `_extract_facts()` and `_log_user_turn_and_condense()`, so the
plain/streaming/tool-calling paths can't drift out of sync with each
other's memory handling.

## Phase 6 notes

Phase 4/5's `ask_with_tools` was a single round: the model could call
tools exactly once per user turn, get the results back, and had to give
its final answer right there. Phase 6 turns that into a loop (in both
`groq_provider.py` and `gemini_provider.py`, each in their own idiom):
model asks for tools -> Lyra runs them -> results go back to the model ->
the model is asked again **with tools still on offer**, so it can chain
further calls (e.g. search for something, then compute on what it found,
then check something else) instead of being cut off after one round.

- `lyra/config.py` adds `MAX_TOOL_ROUNDS` (default 5, overridable via
  `.env`) — the cap on how many rounds of tool calls one request can
  chain through. The loop keeps going as long as the model keeps
  requesting tools; the moment a round comes back with no tool calls,
  that round's text is the final answer.
- If the model is still asking for tools after `MAX_TOOL_ROUNDS` rounds,
  Lyra stops offering tools for one last call (Groq: `tool_choice="none"`;
  Gemini: a tools-less `GenerateContentConfig`) so a runaway chain can't
  hang the request forever — the model has to answer in text using
  whatever it's already gathered. A `round_limit` event fires through
  `on_tool_event` when this happens, so the reasoning-trace panel
  (`lyra/ui/trace_panel.py`) shows the user that the cap was hit rather
  than silently truncating.
- Everything from Phase 4's security rules still applies unchanged every
  round: the tool-safety system prompt, `requires_confirmation` blocking,
  and errors-as-strings instead of raw exceptions.
- No interface changes outside `providers/` — `llm_client.py`, `worker.py`,
  and `main.py` call `ask_with_tools()` exactly as before; the multi-round
  behavior is entirely internal to each provider's implementation.

## What's next (Phase 7+)

Whatever the plan's later phases call for beyond multi-step tool chains.
