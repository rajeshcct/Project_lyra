"""
Phase 3 — Text-to-speech.
-------------------------
A plain, UI-free wrapper around pyttsx3, same shape as stt.py / llm_client.py:
one function, zero PySide6 import, RuntimeError on failure.

pyttsx3's engine is NOT safe to share across threads or across repeated
runAndWait() calls on a long-lived instance (the well-known "runAndWait
called twice" / engine-hangs issue). The reliable pattern is a fresh
engine per utterance, always on the same (background) thread that's going
to run it -- which is exactly what tts_worker.py's QThread gives us, since
each worker run gets its own thread invocation of speak().
"""

import pyttsx3

# pyttsx3's default rate (words per minute) comes from the OS SAPI5 voice
# and is often ~200wpm, which reads as "too fast" for a spoken reply.
# Lowering it here is the single knob that controls playback speed --
# tune this one number if it still feels fast/slow.
TTS_RATE_WPM = 150


def speak(text: str, rate: int = TTS_RATE_WPM) -> None:
    """
    Speak `text` aloud via the OS's TTS voice, blocking until done.

    Meant to be called from a background thread (see tts_worker.py) --
    it blocks for as long as the speech takes, same as ask_llm blocking
    on a network call.
    """
    if not text or not text.strip():
        return

    try:
        engine = pyttsx3.init()
        engine.setProperty("rate", rate)
        engine.say(text)
        engine.runAndWait()
        engine.stop()
    except Exception as e:
        raise RuntimeError(f"Text-to-speech failed: {e}") from e
