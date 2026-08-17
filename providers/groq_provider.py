"""Groq provider — wraps the `groq` SDK behind the LLMProvider interface."""

from .base import LLMProvider
from .registry import register_provider


@register_provider("groq")
class GroqProvider(LLMProvider):
    def ask(self, prompt: str) -> str:
        from groq import Groq
        import groq as groq_sdk

        client = Groq(api_key=self.api_key)

        try:
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
            )
        except groq_sdk.RateLimitError as e:
            raise RuntimeError(
                "Rate limit hit (free tier). Wait a bit and try again."
            ) from e
        except groq_sdk.AuthenticationError as e:
            raise RuntimeError(
                "Groq rejected the API key. Check your .env file."
            ) from e
        except groq_sdk.APIStatusError as e:
            raise RuntimeError(f"Groq rejected the request: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Could not reach Groq: {e}") from e

        text = response.choices[0].message.content
        if not text:
            raise RuntimeError("Groq returned an empty response.")
        return text

    def ask_stream(self, prompt: str):
        from groq import Groq
        import groq as groq_sdk

        client = Groq(api_key=self.api_key)

        try:
            stream = client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )
            got_any = False
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    got_any = True
                    yield delta
            if not got_any:
                raise RuntimeError("Groq returned an empty response.")
        except groq_sdk.RateLimitError as e:
            raise RuntimeError(
                "Rate limit hit (free tier). Wait a bit and try again."
            ) from e
        except groq_sdk.AuthenticationError as e:
            raise RuntimeError(
                "Groq rejected the API key. Check your .env file."
            ) from e
        except groq_sdk.APIStatusError as e:
            raise RuntimeError(f"Groq rejected the request: {e}") from e
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Could not reach Groq: {e}") from e
