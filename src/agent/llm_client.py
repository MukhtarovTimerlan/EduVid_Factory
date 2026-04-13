import os
import time
from dataclasses import dataclass

import openai

from src.utils.exceptions import LLMUnavailableError

_RETRY_BACKOFF = (1, 2, 4)


@dataclass
class LLMResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int


class LLMClient:
    """Thin wrapper around the openai SDK pointed at routerai.ru."""

    def __init__(self, logger=None) -> None:
        self._client = openai.OpenAI(
            base_url=os.environ["ROUTERAI_BASE_URL"],
            api_key=os.environ["ROUTERAI_API_KEY"],
        )
        self._model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        self._temperature = float(os.environ.get("LLM_TEMPERATURE", "0.3"))
        self._max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "1024"))
        self._timeout = int(os.environ.get("LLM_TIMEOUT", "30"))
        self._logger = logger

    def call(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """
        Call the LLM. Retries on transient errors (timeout, 5xx, connection).
        Raises LLMUnavailableError after 3 failed attempts.
        Never logs the API key.
        """
        model = model or self._model
        max_tokens = max_tokens or self._max_tokens
        last_error: Exception | None = None

        for attempt, delay in enumerate(_RETRY_BACKOFF, 1):
            try:
                t0 = time.monotonic()
                resp = self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=self._temperature,
                    timeout=self._timeout,
                )
                latency_ms = int((time.monotonic() - t0) * 1000)
                result = LLMResponse(
                    content=resp.choices[0].message.content or "",
                    prompt_tokens=resp.usage.prompt_tokens,
                    completion_tokens=resp.usage.completion_tokens,
                )
                self._log(
                    "info",
                    f"LLM response | model={model} prompt_tokens={result.prompt_tokens} "
                    f"completion_tokens={result.completion_tokens} latency={latency_ms}ms",
                )
                return result

            except openai.AuthenticationError as e:
                raise LLMUnavailableError(f"LLM auth failed: {e}") from e

            except openai.RateLimitError as e:
                retry_after = 60
                if e.response is not None:
                    retry_after = int(e.response.headers.get("Retry-After", 60))
                self._log("warning", f"LLM rate-limited, waiting {retry_after}s (attempt {attempt}/3)")
                time.sleep(retry_after)
                last_error = e

            except (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError) as e:
                last_error = e
                self._log("warning", f"LLM retry {attempt}/3: {type(e).__name__}: {e}")
                if attempt < len(_RETRY_BACKOFF):
                    time.sleep(delay)

        raise LLMUnavailableError(
            f"LLM unavailable after 3 retries: {last_error}"
        ) from last_error

    def _log(self, level: str, msg: str) -> None:
        if self._logger:
            getattr(self._logger, level)(msg)
