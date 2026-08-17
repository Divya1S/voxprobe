"""Thin Vapi REST client: build a transient assistant from a scenario, place the call, poll, download artifacts.

Field names come from Vapi's OpenAPI spec (https://api.vapi.ai/api-json), checked 2026-08-16.
Only three endpoints are used: POST /call, GET /call/{id}, and artifact downloads — a small surface we
fully understand beats a large SDK we'd have to explain.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import httpx

from .config import Settings, assert_allowed_target
from .scenarios import Scenario
from .targets import Target, VapiConnection

log = logging.getLogger("voxprobe.vapi")

VAPI_API = "https://api.vapi.ai"

# Vapi server messages we want (webhooks). Everything lands in reports/events/<call_id>.jsonl.
SERVER_MESSAGES = ["transcript", "speech-update", "status-update", "end-of-call-report", "user-interrupted", "hang"]

# Phrases that, when OUR patient says them, make Vapi hang up (case-insensitive substring match).
END_CALL_PHRASES = ["goodbye", "bye now", "bye-bye", "bye bye", "take care"]


def build_assistant(scenario: Scenario, target: Target, settings: Settings) -> dict:
    """Transient assistant config for one call. The persona itself lives in our server; Vapi only carries
    the SCENARIO marker, the audio-layer settings, and where to reach us."""
    if not settings.public_base_url:
        raise RuntimeError("PUBLIC_BASE_URL is not set — start the tunnel first")
    p = scenario.patient
    assistant: dict = {
        "name": f"voxprobe-patient-{scenario.id}",
        # We are calling THEM: the receptionist answers and talks first; our patient listens, then replies.
        "firstMessageMode": "assistant-waits-for-user",
        "model": {
            "provider": "custom-llm",
            "url": settings.public_base_url,  # Vapi appends /chat/completions
            "model": "voxprobe-patient-brain",
            "messages": [{"role": "system", "content": f"SCENARIO:{scenario.id} TARGET:{target.id}"}],
            "temperature": 0.7,
            "maxTokens": 90,
            "timeoutSeconds": 15,
            "metadataSendMode": "off",
        },
        # Bearer token Vapi sends to /chat/completions
        "credentials": [{"provider": "custom-llm", "apiKey": settings.brain_server_secret, "name": "voxprobe-brain"}],
        # STT of the receptionist's speech. Deepgram BYO key is registered in the Vapi dashboard.
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-3",
            "language": "en",
            "smartFormat": False,
            "endpointing": 300,
            "keyterm": [target.business.name, *[pr.split("(")[0].strip() for pr in target.business.providers], p.name],
        },
        # Our patient's voice
        "voice": {"provider": "deepgram", "model": "aura-2", "voiceId": p.voice_id},
        # Webhooks → our server (same tunnel)
        "server": {
            "url": f"{settings.public_base_url}/vapi/webhook",
            "timeoutSeconds": 10,
            "headers": {"Authorization": f"Bearer {settings.brain_server_secret}"},
        },
        "serverMessages": SERVER_MESSAGES,
        "artifactPlan": {"recordingEnabled": True, "recordingFormat": "mp3"},
        "monitorPlan": {"controlEnabled": True, "listenEnabled": False},
        "startSpeakingPlan": {"waitSeconds": 0.5, "smartEndpointingPlan": {"provider": "livekit"}},
        "backgroundSound": "off",
        "endCallPhrases": END_CALL_PHRASES,
        "maxDurationSeconds": scenario.max_duration_seconds,
        "metadata": {"scenario_id": scenario.id, "target_id": target.id, "project": "voxprobe"},
    }
    if scenario.barge_in:
        # Deliberate interruption testing: let the patient cut in fast; the director drives WHEN (see server).
        assistant["stopSpeakingPlan"] = {"numWords": 1, "voiceSeconds": 0.1, "backoffSeconds": 0.5}
    return assistant


class VapiClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._http = httpx.AsyncClient(
            base_url=VAPI_API,
            headers={"Authorization": f"Bearer {settings.vapi_api_key}", "Content-Type": "application/json"},
            timeout=30,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def create_call(self, scenario: Scenario, target: Target) -> dict:
        """Place the outbound call. The destination MUST pass the allow-list guard — no exceptions."""
        if not isinstance(target.connection, VapiConnection):
            raise RuntimeError(f"target {target.id} is not a vapi phone target")
        self.settings.require_vapi()
        to = assert_allowed_target(target.connection.phone_number, self.settings.allowed_numbers)  # the single choke point
        payload = {
            "name": f"{scenario.id}@{target.id}",
            "phoneNumberId": self.settings.vapi_phone_number_id,
            "customer": {"number": to, "name": target.name},
            "assistant": build_assistant(scenario, target, self.settings),
        }
        r = await self._http.post("/call", json=payload)
        if r.status_code >= 300:
            raise RuntimeError(f"Vapi create call failed {r.status_code}: {r.text[:800]}")
        call = r.json()
        log.info("call created id=%s status=%s from=%s to=%s", call.get("id"), call.get("status"),
                 self.settings.caller_number, to)
        return call

    async def get_call(self, call_id: str) -> dict:
        r = await self._http.get(f"/call/{call_id}")
        r.raise_for_status()
        return r.json()

    async def wait_until_ended(self, call_id: str, timeout_s: int = 900, poll_s: float = 3.0) -> dict:
        """Poll until status == 'ended' (or timeout). Prints status transitions."""
        t0 = time.monotonic()
        last = None
        while time.monotonic() - t0 < timeout_s:
            call = await self.get_call(call_id)
            status = call.get("status")
            if status != last:
                log.info("call %s status: %s", call_id[:8], status)
                last = status
            if status == "ended":
                return call
            await asyncio.sleep(poll_s)
        raise TimeoutError(f"call {call_id} did not end within {timeout_s}s")

    async def wait_for_artifacts(self, call_id: str, timeout_s: int = 120) -> dict:
        """Recording URLs appear a little after the call ends; poll for them."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout_s:
            call = await self.get_call(call_id)
            art = call.get("artifact") or {}
            if art.get("stereoRecordingUrl") or (art.get("recording") or {}).get("stereoUrl"):
                return call
            await asyncio.sleep(3)
        return await self.get_call(call_id)

    async def download(self, url: str, dest: Path) -> Path:
        """Download an artifact. Presigned URLs need no auth; stable URLs may — try both."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as anon:
            r = await anon.get(url)
            if r.status_code == 200:
                dest.write_bytes(r.content)
                return dest
        r = await self._http.get(url)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return dest

    async def control(self, call: dict, message: dict) -> None:
        """Live call control (e.g. {"type": "say", "content": "..."} or {"type": "end-call"})."""
        url = (call.get("monitor") or {}).get("controlUrl")
        if not url:
            raise RuntimeError("call has no monitor.controlUrl (monitorPlan.controlEnabled?)")
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(url, json=message)
            r.raise_for_status()
