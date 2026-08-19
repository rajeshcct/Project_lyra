"""
Central LLM config for Project Lyra.
-------------------------------------
Switch providers by changing LLM_PROVIDER in .env (or the default below) —
no other file needs to change. llm_client.py reads from here.

Supported providers: "gemini", "groq"
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Which provider to use. Override via .env: LLM_PROVIDER=gemini or LLM_PROVIDER=groq
PROVIDER = os.environ.get("LLM_PROVIDER", "groq").strip().lower()

# Per-provider settings: which env var holds the key, and which model to call.
# Model names checked current as of Aug 2026 — verify against the provider's
# docs if you hit a 404 again (models get deprecated on a rolling basis).
PROVIDERS = {
    "gemini": {
        "api_key_env": "GEMINI_API_KEY",
        "model": "gemini-3.7-flash",
    },
    "groq": {
        "api_key_env": "GROQ_API_KEY",
        # llama-3.3-70b-versatile was announced deprecated by Groq on
        # 2026-06-17; openai/gpt-oss-120b is their recommended replacement
        # (faster + similar quality). Swap to "openai/gpt-oss-20b" for a
        # cheaper/faster-but-lighter option.
        "model": "openai/gpt-oss-120b",
    },
}

if PROVIDER not in PROVIDERS:
    raise RuntimeError(
        f"Unknown LLM_PROVIDER '{PROVIDER}' in .env. "
        f"Valid options: {', '.join(PROVIDERS)}"
    )

_cfg = PROVIDERS[PROVIDER]
MODEL_NAME = _cfg["model"]
API_KEY_ENV = _cfg["api_key_env"]
API_KEY = os.environ.get(API_KEY_ENV)

if not API_KEY:
    raise RuntimeError(
        f"{API_KEY_ENV} not found for provider '{PROVIDER}'.\n"
        "1) Copy .env.example to .env (if you haven't)\n"
        f"2) Paste your real {PROVIDER} API key into {API_KEY_ENV}\n"
        "3) Or switch LLM_PROVIDER in .env to a provider you have a key for"
    )
