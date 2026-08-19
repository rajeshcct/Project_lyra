"""Gemini provider — wraps the `google-genai` SDK behind the LLMProvider interface."""

from .base import LLMProvider
from .registry import register_provider


@register_provider("gemini")
class GeminiProvider(LLMProvider):
    def ask(self, prompt: str) -> str:
        from google import genai
        from google.genai import errors as genai_errors

        client = genai.Client(api_key=self.api_key)

        try:
            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
        except genai_errors.ClientError as e:
            if getattr(e, "code", None) == 429:
                raise RuntimeError(
                    "Rate limit hit (free tier). Wait a bit and try again."
                ) from e
            if getattr(e, "code", None) in (401, 403):
                raise RuntimeError(
                    "Gemini rejected the API key. Check your .env file."
                ) from e
            raise RuntimeError(f"Gemini rejected the request: {e}") from e
        except genai_errors.ServerError as e:
            raise RuntimeError(f"Gemini server error — try again shortly: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Could not reach Gemini: {e}") from e

        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini returned an empty response.")
        return text

    def ask_stream(self, prompt: str):
        from google import genai
        from google.genai import errors as genai_errors

        client = genai.Client(api_key=self.api_key)

        try:
            stream = client.models.generate_content_stream(
                model=self.model_name,
                contents=prompt,
            )
            got_any = False
            for chunk in stream:
                text = getattr(chunk, "text", None)
                if text:
                    got_any = True
                    yield text
            if not got_any:
                raise RuntimeError("Gemini returned an empty response.")
        except genai_errors.ClientError as e:
            if getattr(e, "code", None) == 429:
                raise RuntimeError(
                    "Rate limit hit (free tier). Wait a bit and try again."
                ) from e
            if getattr(e, "code", None) in (401, 403):
                raise RuntimeError(
                    "Gemini rejected the API key. Check your .env file."
                ) from e
            raise RuntimeError(f"Gemini rejected the request: {e}") from e
        except genai_errors.ServerError as e:
            raise RuntimeError(f"Gemini server error — try again shortly: {e}") from e
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Could not reach Gemini: {e}") from e
