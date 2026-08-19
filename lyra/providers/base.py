"""
Common contract every LLM provider must implement.

Any new provider — Groq, Gemini, OpenAI, a local model, whatever — is just a
class in this package that subclasses LLMProvider and implements ask().
Nothing outside providers/ ever imports a provider-specific SDK directly.
"""

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """One provider = one API key + one model + one ask() implementation."""

    def __init__(self, api_key: str, model_name: str):
        self.api_key = api_key
        self.model_name = model_name

    @abstractmethod
    def ask(self, prompt: str) -> str:
        """
        Send `prompt` to this provider and return the reply text.

        Implementations MUST catch their SDK's own exceptions and re-raise
        as RuntimeError with a short, human-readable message — callers
        (the CLI in test_llm.py, the QThread in worker.py) only ever catch
        RuntimeError and show str(e) directly in the UI.
        """
        raise NotImplementedError

    @abstractmethod
    def ask_stream(self, prompt: str):
        """
        Send `prompt` to this provider and yield reply text chunks as they
        arrive, instead of blocking for the full reply.

        Same RuntimeError contract as ask(): implementations MUST catch
        their SDK's own exceptions (including ones raised mid-stream) and
        re-raise as RuntimeError. Callers only ever catch RuntimeError.
        """
        raise NotImplementedError
