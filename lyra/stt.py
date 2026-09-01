"""
Phase 3 — Speech-to-text.
-------------------------
A plain, UI-free wrapper around SpeechRecognition + PyAudio, mirroring
llm_client.py's shape on purpose: one function, zero PySide6 import, and
every failure mode (no mic, silence timeout, unintelligible audio, no
internet) collapses to RuntimeError with a human-readable message. Callers
(mic_worker.py's QThread) only ever need to catch RuntimeError, same
contract as ask_llm / ask_llm_stream.

Uses the free Google Web Speech API via SpeechRecognition's built-in
recognize_google() -- no API key needed, consistent with the project
running on free-tier services throughout.
"""

import speech_recognition as sr

# Tunable listening limits. phrase_time_limit caps how long a single
# utterance can run so a mistaken open mic doesn't record forever;
# timeout caps how long we wait for speech to *start* before giving up.
LISTEN_TIMEOUT_SECONDS = 6
PHRASE_TIME_LIMIT_SECONDS = 15


def listen_once(
    timeout: float = LISTEN_TIMEOUT_SECONDS,
    phrase_time_limit: float = PHRASE_TIME_LIMIT_SECONDS,
) -> str:
    """
    Capture one utterance from the default microphone and return the
    recognized text.

    Raises RuntimeError (never the raw SDK/OS exception) with a short,
    human-readable message for every failure mode: no microphone hardware,
    nobody spoke before `timeout`, speech that couldn't be understood, or
    no network reachable for the recognition API call.
    """
    recognizer = sr.Recognizer()

    try:
        with sr.Microphone() as source:
            # Half a second of ambient-noise calibration makes a real
            # difference in noisy rooms and costs almost nothing in
            # wall-clock time compared to getting a garbled transcript back.
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            try:
                audio = recognizer.listen(
                    source, timeout=timeout, phrase_time_limit=phrase_time_limit
                )
            except sr.WaitTimeoutError as e:
                raise RuntimeError("Didn't hear anything — try again.") from e
    except OSError as e:
        # PyAudio raises OSError when there's no input device at all, or
        # the OS denies mic access (e.g. Windows privacy settings).
        raise RuntimeError(
            "Couldn't access the microphone. Check that one is connected "
            "and that this app has microphone permission."
        ) from e

    try:
        text = recognizer.recognize_google(audio)
    except sr.UnknownValueError as e:
        raise RuntimeError("Couldn't make out what you said — try again.") from e
    except sr.RequestError as e:
        raise RuntimeError(f"Speech recognition service unreachable: {e}") from e

    if not text or not text.strip():
        raise RuntimeError("Couldn't make out what you said — try again.")

    return text
