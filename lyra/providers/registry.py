"""
Provider registry.

A plain name -> class lookup. Provider modules register themselves into
this via the @register_provider decorator when they're imported (see the
auto-discovery in providers/__init__.py). This file has zero knowledge of
which providers actually exist — that's the whole point.
"""

from .base import LLMProvider

_REGISTRY: dict[str, type[LLMProvider]] = {}


def register_provider(name: str):
    """Class decorator: @register_provider("groq") on an LLMProvider subclass."""

    def _wrap(cls: type[LLMProvider]) -> type[LLMProvider]:
        _REGISTRY[name] = cls
        return cls

    return _wrap


def get_provider(name: str, api_key: str, model_name: str) -> LLMProvider:
    """Instantiate the provider registered under `name`."""
    try:
        provider_cls = _REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY)) or "(none discovered)"
        raise RuntimeError(
            f"No provider implementation registered for '{name}'. "
            f"Available: {available}"
        )
    return provider_cls(api_key=api_key, model_name=model_name)
