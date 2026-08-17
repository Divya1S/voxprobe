"""The patient's brain: turn conversation history into the next 1–2 spoken sentences, fast and never silent.

Design:
* One OpenAI-compatible client per provider (Groq primary, Gemini failover). Same request shape for both,
  so failover = "next provider in the list", not "different library".
* Generate the whole reply, then post-process (strip markdown, cap sentences), then hand it to the
  server which emits it as SSE. At Groq speed the buffering costs tens of milliseconds and buys us
  control over what actually gets spoken.
* Every turn records provider, time-to-reply, prompt/completion tokens (from the API when reported)
  — that is our latency/TPM evidence.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError

from .config import Settings

log = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# History window: keep the last N non-system messages. Short enough for free-tier TPM, long enough that
# the patient remembers what was just established (name, DOB, offered slot).
HISTORY_WINDOW = 10
MAX_REPLY_TOKENS = 90
MAX_SENTENCES = 3
FIRST_TOKEN_TIMEOUT_S = 8.0


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str
    extra: dict = field(default_factory=dict)  # provider-specific request kwargs


@dataclass
class TurnRecord:
    provider: str
    model: str
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    reply: str
    failed_over_from: list[str] = field(default_factory=list)


def _groq_extra(model: str) -> dict:
    # gpt-oss models "think" before answering; keep that short — we need speed, not depth
    return {"reasoning_effort": "low"} if model.startswith("openai/gpt-oss") else {}


def build_providers(settings: Settings) -> list[Provider]:
    """Failover order: Groq primary → Groq fallback model (separate TPM bucket) → Gemini."""
    providers: list[Provider] = []
    if settings.groq_api_key:
        providers.append(
            Provider(
                "groq", GROQ_BASE_URL, settings.groq_api_key, settings.groq_model, _groq_extra(settings.groq_model)
            )
        )
        if settings.groq_fallback_model and settings.groq_fallback_model != settings.groq_model:
            providers.append(
                Provider(
                    "groq-fallback",
                    GROQ_BASE_URL,
                    settings.groq_api_key,
                    settings.groq_fallback_model,
                    _groq_extra(settings.groq_fallback_model),
                )
            )
    if settings.google_api_key:
        providers.append(Provider("gemini", GEMINI_BASE_URL, settings.google_api_key, settings.gemini_model))
    if not providers:
        raise RuntimeError("No LLM provider configured: set GROQ_API_KEY and/or GOOGLE_API_KEY")
    return providers


_MD = re.compile(r"[*_`#>]+")
_STAGE = re.compile(r"\((?:[a-z ]{1,25})\)")  # "(laughs)", "(pauses)" — never spoken by a real caller
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def shape_reply(text: str) -> str:
    """Make the model's text speakable: no markdown, no stage directions, at most MAX_SENTENCES sentences."""
    t = _MD.sub("", text).strip()
    t = _STAGE.sub("", t)
    t = t.replace('"', "").replace("“", "").replace("”", "").strip()
    # models sometimes prefix the speaker name — a phone caller never does
    t = re.sub(r"^(patient|caller|[A-Z][a-z]+ [A-Z][a-z]+):\s*", "", t)
    sentences = _SENT_SPLIT.split(t)
    if len(sentences) > MAX_SENTENCES:
        t = " ".join(sentences[:MAX_SENTENCES])
    return re.sub(r"\s+", " ", t).strip()


def window_history(messages: list[dict]) -> list[dict]:
    """Drop the incoming system message(s) (we supply our own) and keep the last HISTORY_WINDOW turns."""
    convo = [m for m in messages if m.get("role") in ("user", "assistant") and m.get("content")]
    return convo[-HISTORY_WINDOW:]


class Brain:
    def __init__(self, providers: list[Provider]):
        self.providers = providers
        self._clients = {
            p.name: AsyncOpenAI(base_url=p.base_url, api_key=p.api_key, timeout=FIRST_TOKEN_TIMEOUT_S, max_retries=0)
            for p in providers
        }

    async def reply(self, system_prompt: str, history: list[dict]) -> TurnRecord:
        """Produce the next patient utterance. Tries providers in order; raises only if all fail."""
        messages = [{"role": "system", "content": system_prompt}, *history]
        failed: list[str] = []
        last_error: Exception | None = None
        for p in self.providers:
            t0 = time.perf_counter()
            try:
                resp = await self._clients[p.name].chat.completions.create(
                    model=p.model,
                    messages=messages,
                    max_tokens=MAX_REPLY_TOKENS,
                    temperature=0.7,
                    **p.extra,
                )
                raw = (resp.choices[0].message.content or "").strip()
                usage = getattr(resp, "usage", None)
                record = TurnRecord(
                    provider=p.name,
                    model=p.model,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                    prompt_tokens=getattr(usage, "prompt_tokens", None),
                    completion_tokens=getattr(usage, "completion_tokens", None),
                    reply=shape_reply(raw) or "Sorry, could you say that again?",
                    failed_over_from=failed,
                )
                return record
            except (RateLimitError, APITimeoutError, APIConnectionError, APIStatusError) as e:
                last_error = e
                failed.append(p.name)
                log.warning(
                    "provider %s failed (%s) after %d ms — failing over",
                    p.name,
                    type(e).__name__,
                    int((time.perf_counter() - t0) * 1000),
                )
                continue
        raise RuntimeError(f"all LLM providers failed: {failed}") from last_error
