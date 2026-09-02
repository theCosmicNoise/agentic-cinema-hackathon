"""
Gemini access layer.

Two things this hides from the agents:

1. Model availability is not stable. Pro tiers are quota-gated on a free key
   (429) and flash aliases intermittently return 503. A clearance run that dies
   halfway because one model id blinked is worthless, so every call walks a
   fallback chain.
2. Structured output. Agents ask for a Pydantic type back and get it, or a
   typed failure — never a half-parsed string.
3. Thinking budget. Gemini 3.x enables extended thinking by default, which on
   a metered key both stalls long extraction calls and burns the token quota
   (observed: default thinking hangs past 70s or returns 429; the identical
   call with thinking disabled returns in ~3s). Extraction is a mechanical
   task, so it runs with thinking off; only adjudication buys reasoning.
4. Hard timeouts. The SDK's own HttpOptions timeout is not honoured on this
   path — observed requests stall indefinitely after the endpoint returns a
   503. Every attempt therefore runs under a wall-clock deadline enforced
   here, so a hung model fails over instead of freezing the run.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from clearcut.core.config import get_settings
from clearcut.services.cache import DiskCache

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_RETRYABLE = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "500", "INTERNAL",
              "timeout", "Timeout", "ReadTimeout", "ConnectError")


class GeminiUnavailable(RuntimeError):
    """Every model in the fallback chain failed."""


class GeminiClient:
    def __init__(self) -> None:
        s = get_settings()
        # An explicit timeout is load-bearing: without it a stalled request
        # hangs the whole clearance run instead of failing over to the next model.
        http = types.HttpOptions(timeout=60_000)  # milliseconds
        if s.use_vertex:
            self._client = genai.Client(
                vertexai=True,
                project=s.google_cloud_project,
                location=s.google_cloud_location,
                http_options=http,
            )
        else:
            self._client = genai.Client(api_key=s.require_google(), http_options=http)
        self._chain = list(s.gemini_fallbacks)
        self._cache = DiskCache(s.data_dir, "gemini")
        self._lock = threading.Lock()
        # A model that is quota-exhausted stays exhausted for a while. Retrying
        # it on every subsequent call burns ~5s each time, so a model that fails
        # repeatedly is demoted to the back of the chain for the rest of the run.
        self._strikes: dict[str, int] = {}
        self.calls = 0

    # ------------------------------------------------------------------ #
    def generate_structured(
        self,
        *,
        prompt: str,
        schema: type,
        system: str | None = None,
        temperature: float = 0.1,
        thinking_budget: int = 0,
        max_attempts_per_model: int = 2,
    ):
        """Return `schema`-shaped data, walking the fallback chain on failure."""
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=temperature,
            system_instruction=system,
            thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
        )
        ck = self._cache.key(
            {
                "kind": "structured", "prompt": prompt, "system": system,
                "schema": str(schema), "temperature": temperature,
                "thinking": thinking_budget, "chain": self._chain,
            }
        )
        if (cached := self._cache.get(ck)) is not None:
            return cached

        raw = self._call(prompt=prompt, config=cfg, max_attempts=max_attempts_per_model)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GeminiUnavailable(f"Model returned non-JSON: {exc}") from exc
        self._cache.put(ck, parsed)
        return parsed

    def generate_text(
        self,
        *,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.2,
        thinking_budget: int = 0,
    ) -> str:
        cfg = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system,
            thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
        )
        ck = self._cache.key(
            {
                "kind": "text", "prompt": prompt, "system": system,
                "temperature": temperature, "thinking": thinking_budget,
                "chain": self._chain,
            }
        )
        if (cached := self._cache.get(ck)) is not None:
            return cached
        out = self._call(prompt=prompt, config=cfg, max_attempts=2)
        self._cache.put(ck, out)
        return out

    # ------------------------------------------------------------------ #
    def _call(
        self, *, prompt: str, config, max_attempts: int, deadline: float = 45.0
    ) -> str:
        last: Exception | None = None
        for model in self._order():
            for attempt in range(max_attempts):
                try:
                    resp = self._with_deadline(model, prompt, config, deadline)
                    with self._lock:
                        self.calls += 1
                        self._strikes.pop(model, None)
                    if model != self._chain[0]:
                        logger.info("Gemini served by fallback model %s", model)
                    return resp.text or ""
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    msg = str(exc)
                    with self._lock:
                        self._strikes[model] = self._strikes.get(model, 0) + 1
                    # Some models reject thinking_config outright. Strip it and
                    # give this model one more chance before moving on.
                    if "INVALID_ARGUMENT" in msg and config.thinking_config is not None:
                        logger.info("%s rejected thinking_config; retrying without", model)
                        config = config.model_copy(update={"thinking_config": None})
                        continue
                    if not any(code in msg for code in _RETRYABLE):
                        logger.warning("Gemini %s non-retryable: %s", model, msg[:160])
                        break  # bad request — next model won't help either
                    sleep = 1.5 * (attempt + 1)
                    logger.info(
                        "Gemini %s attempt %d failed (%s); retrying in %.1fs",
                        model, attempt + 1, msg[:80], sleep,
                    )
                    time.sleep(sleep)
        raise GeminiUnavailable(f"All models exhausted. Last error: {last}")

    _STRIKE_LIMIT = 2

    def _order(self) -> list[str]:
        """Healthy models first, repeatedly-failing ones last."""
        with self._lock:
            strikes = dict(self._strikes)
        healthy = [m for m in self._chain if strikes.get(m, 0) < self._STRIKE_LIMIT]
        sick = [m for m in self._chain if strikes.get(m, 0) >= self._STRIKE_LIMIT]
        return healthy + sick

    def _with_deadline(self, model: str, prompt: str, config, deadline: float):
        """Run one generate_content under a wall-clock deadline.

        A stalled request is abandoned rather than waited on. The worker thread
        is a daemon, so an orphaned call cannot keep the process alive.
        """
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gemini")
        try:
            future = pool.submit(
                self._client.models.generate_content,
                model=model, contents=prompt, config=config,
            )
            try:
                return future.result(timeout=deadline)
            except FutureTimeout as exc:
                raise TimeoutError(
                    f"gemini {model} exceeded {deadline:.0f}s deadline"
                ) from exc
        finally:
            pool.shutdown(wait=False, cancel_futures=True)


_client: GeminiClient | None = None


def get_gemini() -> GeminiClient:
    global _client
    if _client is None:
        _client = GeminiClient()
    return _client
