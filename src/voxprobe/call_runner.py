"""Orchestrate one real call end-to-end: preflight → dial → wait → download → evidence bundle.

`run_call` assumes the brain server is reachable at settings.public_base_url (see cli.py `run`, which
also starts the tunnel and the server in-process, or `call`, which expects them running already).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

import httpx

from .config import Settings, assert_allowed_target
from .evidence import artifact_stem, write_bundle
from .scenarios import Scenario
from .targets import Target, VapiConnection
from .vapi_client import VapiClient

log = logging.getLogger("voxprobe.runner")


async def preflight(settings: Settings, scenario: Scenario, target: Target) -> None:
    """Fail fast on anything that would waste a call. Checked BEFORE the phone adapter is contacted."""
    if not isinstance(target.connection, VapiConnection):
        raise RuntimeError(
            f"target {target.id} is a {target.kind} target; use `voxprobe run --target <local target>` for it"
        )
    assert_allowed_target(target.connection.phone_number, settings.allowed_numbers)
    if not settings.public_base_url.startswith("https://"):
        raise RuntimeError(f"PUBLIC_BASE_URL must be an https tunnel URL, got {settings.public_base_url!r}")
    if not settings.brain_server_secret:
        raise RuntimeError("BRAIN_SERVER_SECRET is empty — refusing to expose an unauthenticated brain server")
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{settings.public_base_url}/health")
        if r.status_code != 200 or not r.json().get("ok"):
            raise RuntimeError(f"brain server not healthy through the tunnel: {r.status_code} {r.text[:200]}")
    log.info(
        "preflight ok: %s reachable, scenario %s, caller %s → target %s (%s)",
        settings.public_base_url,
        scenario.id,
        settings.caller_number,
        target.id,
        target.connection.phone_number,
    )


async def run_call(settings: Settings, scenario: Scenario, target: Target, analyze: bool = True) -> dict:
    await preflight(settings, scenario, target)
    client = VapiClient(settings)
    try:
        call = await client.create_call(scenario, target)
        call_id = call["id"]
        print(
            f"\n▶ call {call_id} placed: {settings.caller_number} → {target.connection.phone_number}  [{scenario.id} @ {target.id}]"
        )
        call = await client.wait_until_ended(call_id, timeout_s=scenario.max_duration_seconds + 180)
        print(f"■ call ended: reason={call.get('endedReason')}  cost=${call.get('cost')}")

        call = await client.wait_for_artifacts(call_id)
        art = call.get("artifact") or {}
        stem = artifact_stem(scenario, call)

        # stereo recording (LEFT = agent/customer, RIGHT = patient/assistant)
        mp3_path: Path | None = None
        stereo_url = (
            art.get("presignedStereoUrl")
            or art.get("stereoRecordingUrl")
            or (art.get("recording") or {}).get("stereoUrl")
        )
        if stereo_url:
            mp3_path = await client.download(stereo_url, settings.recordings_dir / f"{stem}.mp3")
            print(f"● stereo recording → {mp3_path.relative_to(settings.repo_root)}")
        else:
            print("! no stereo recording URL in artifact (yet)")

        # per-channel mono files (handy for per-side re-transcription); kept out of git via recordings/raw/
        mono_paths: dict[str, Path] = {}
        mono = (art.get("recording") or {}).get("mono") or {}
        for key, label in (("customerUrl", "agent"), ("assistantUrl", "patient")):
            url = art.get(f"presigned{'Customer' if key == 'customerUrl' else 'Assistant'}Url") or mono.get(key)
            if url:
                try:
                    mono_paths[label] = await client.download(
                        url, settings.recordings_dir / "raw" / f"{stem}-{label}.mp3"
                    )
                except Exception as e:  # non-fatal: stereo is the deliverable
                    log.warning("mono %s download failed: %s", label, e)

        meta = write_bundle(settings, scenario, target, call, mp3_path, mono_paths)
        print(f"● transcript → {meta['files']['transcript_md']}")
        print(f"● meta       → {meta['files']['meta_json']}   audio={meta['audio']}")
        if mp3_path and analyze:
            try:
                from .analyze import analyze_call

                out = analyze_call(settings, meta["stem"])
                print(f"● analysis   → {out.relative_to(settings.repo_root)}")
            except Exception as e:  # analysis is best-effort; the recording is the deliverable
                log.warning("post-call analysis failed: %s (run `voxprobe analyze %s` later)", e, meta["stem"])
        return meta
    finally:
        await client.aclose()


def with_public_url(settings: Settings, url: str) -> Settings:
    return replace(settings, public_base_url=url.rstrip("/"))
