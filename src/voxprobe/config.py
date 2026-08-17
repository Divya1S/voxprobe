"""Configuration and safety guards.

Everything secret or environment-specific comes from environment variables (loaded from .env for local
runs). Two things are deliberate design choices:

* **Dial allow-list.** voxprobe can place real phone calls (optional phone adapters). To make it impossible to
  dial the wrong number by accident (a typo in a target file, a stale env var), every outbound number must pass
  :func:`assert_allowed_target`, which checks it against ``ALLOWED_NUMBERS_E164`` from the environment. A target
  file *and* the environment must agree before a call is placed. Local/websocket targets never dial anything.
* **Fixed evidence layout** (recordings/, transcripts/, reports/) so every run's artifacts land in the same place.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_E164 = re.compile(r"^\+[1-9]\d{6,14}$")


class TargetNumberError(RuntimeError):
    """Raised when something tries to dial a number that is not on the allow-list."""


def normalize_e164(number: str) -> str:
    """Normalize human-typed numbers like '+1 (555) 010-1234' to strict E.164 '+15550101234'."""
    digits = re.sub(r"[^\d+]", "", number.strip())
    if not digits.startswith("+"):
        digits = "+" + digits
    if not _E164.match(digits):
        raise ValueError(f"not a valid E.164 number: {number!r}")
    return digits


def parse_allowlist(raw: str) -> frozenset[str]:
    return frozenset(normalize_e164(n) for n in raw.split(",") if n.strip())


def assert_allowed_target(number: str, allowed: frozenset[str]) -> str:
    """Return the normalized number if — and only if — it is on the allow-list.

    This is the single choke point for outbound dialing. Keep it boring and un-bypassable.
    """
    normalized = normalize_e164(number)
    if normalized not in allowed:
        raise TargetNumberError(
            f"Refusing to dial {normalized}: not in ALLOWED_NUMBERS_E164 ({sorted(allowed) or 'empty'})"
        )
    return normalized


def _repo_root() -> Path:
    # src/voxprobe/config.py -> repo root is two levels up from the package directory
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from the environment. Immutable after creation."""

    # LLM providers (simulator brain + judge). Groq primary, Groq fallback model, Gemini failover.
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_fallback_model: str = "llama-3.1-8b-instant"
    google_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"

    # speech (used by the audio arena and by phone adapters that support bring-your-own keys)
    deepgram_api_key: str = ""

    # brain server (only needed by phone adapters that call back into a custom-LLM endpoint)
    public_base_url: str = ""
    brain_server_secret: str = ""
    brain_host: str = "127.0.0.1"
    brain_port: int = 8000

    # optional phone adapter: Vapi
    vapi_api_key: str = ""
    vapi_phone_number_id: str = ""
    caller_number: str = ""

    # dial guard
    allowed_numbers: frozenset[str] = frozenset()

    repo_root: Path = field(default_factory=_repo_root)

    @property
    def recordings_dir(self) -> Path:
        return self.repo_root / "recordings"

    @property
    def transcripts_dir(self) -> Path:
        return self.repo_root / "transcripts"

    @property
    def reports_dir(self) -> Path:
        return self.repo_root / "reports"

    @property
    def scenarios_dir(self) -> Path:
        return self.repo_root / "scenarios"

    @property
    def targets_dir(self) -> Path:
        return self.repo_root / "targets"

    def require_vapi(self) -> None:
        missing = [n for n, v in (("VAPI_API_KEY", self.vapi_api_key), ("VAPI_PHONE_NUMBER_ID", self.vapi_phone_number_id))
                   if not v]
        if missing:
            raise RuntimeError(f"Vapi phone adapter needs {missing} (see .env.example)")


def load_settings() -> Settings:
    """Load settings from the environment (and .env if present). Never raises for missing optional adapters."""
    load_dotenv(_repo_root() / ".env", override=False)
    env = os.environ.get
    caller = env("CALLER_NUMBER_E164", "").strip()
    return Settings(
        groq_api_key=env("GROQ_API_KEY", ""),
        groq_model=env("GROQ_MODEL", "llama-3.3-70b-versatile"),
        groq_fallback_model=env("GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant"),
        google_api_key=env("GOOGLE_API_KEY", ""),
        gemini_model=env("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        deepgram_api_key=env("DEEPGRAM_API_KEY", ""),
        public_base_url=env("PUBLIC_BASE_URL", "").rstrip("/"),
        brain_server_secret=env("BRAIN_SERVER_SECRET", ""),
        brain_host=env("BRAIN_HOST", "127.0.0.1"),
        brain_port=int(env("BRAIN_PORT", "8000")),
        vapi_api_key=env("VAPI_API_KEY", ""),
        vapi_phone_number_id=env("VAPI_PHONE_NUMBER_ID", ""),
        caller_number=normalize_e164(caller) if caller else "",
        allowed_numbers=parse_allowlist(env("ALLOWED_NUMBERS_E164", "")),
    )
