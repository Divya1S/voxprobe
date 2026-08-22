"""The inbound line: our receptionist under test answering a real phone number, so an outside caller (CALL-E) can dial it.

``line up``    start the brain server + tunnel, upsert the saved Vapi assistant ``voxprobe-line`` (custom-LLM → our server
               in receptionist role, Deepgram BYO, stereo MP3), point the free number at it, write reports/line/state.json,
               and stay up until Ctrl-C.
``line arm``   re-point the saved assistant at another target/greeting/scenario while the line is up (one PATCH).
``line fetch`` pull recent calls to the line, download the stereo MP3, swap channels into voxprobe's convention
               (L = agent under test = our receptionist, R = caller), and write the evidence bundle so ``voxprobe analyze``
               works unchanged.
``line down``  detach the assistant from the number.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .evidence import probe_audio
from .scenarios import find_scenario
from .targets import Target, find_target
from .vapi_client import LINE_ASSISTANT_NAME, VapiClient, build_line_assistant

log = logging.getLogger("voxprobe.line")


@dataclass
class LineState:
    public_url: str
    assistant_id: str
    phone_number_id: str
    number: str
    target_id: str
    scenario_id: str
    greeting: str
    since: float

    def save(self, settings: Settings) -> Path:
        p = settings.reports_dir / "line" / "state.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.__dict__, indent=2))
        return p

    @classmethod
    def load(cls, settings: Settings) -> LineState:
        p = settings.reports_dir / "line" / "state.json"
        if not p.exists():
            raise RuntimeError("line is not up (no reports/line/state.json) — run `voxprobe line up` first")
        return cls(**json.loads(p.read_text()))


def with_public_url(settings: Settings, url: str) -> Settings:
    from dataclasses import replace

    return replace(settings, public_base_url=url.rstrip("/"))


async def arm(settings: Settings, target: Target, *, scenario_id: str = "", greeting: str | None = None) -> LineState:
    """Upsert the saved assistant for this target and make sure the number points at it."""
    settings.require_vapi()
    client = VapiClient(settings)
    try:
        body = build_line_assistant(target, settings, scenario_id=scenario_id, greeting=greeting)
        assistant = await client.upsert_assistant(body)
        number = await client.get_phone_number(settings.vapi_phone_number_id)
        if number.get("assistantId") != assistant["id"]:
            number = await client.patch_phone_number(settings.vapi_phone_number_id, {"assistantId": assistant["id"]})
    finally:
        await client.aclose()
    state = LineState(
        public_url=settings.public_base_url,
        assistant_id=assistant["id"],
        phone_number_id=settings.vapi_phone_number_id,
        number=number.get("number") or "",
        target_id=target.id,
        scenario_id=scenario_id,
        greeting=body["firstMessage"],
        since=time.time(),
    )
    state.save(settings)
    return state


async def down(settings: Settings) -> None:
    settings.require_vapi()
    client = VapiClient(settings)
    try:
        await client.patch_phone_number(settings.vapi_phone_number_id, {"assistantId": None})
    finally:
        await client.aclose()


def _swap_channels(src: Path, dst: Path) -> Path:
    """Vapi inbound stereo = L caller / R assistant. voxprobe's convention = L agent under test / R caller. Swap."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-af",
            "pan=stereo|c0=c1|c1=c0",
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(dst),
        ],
        check=True,
    )
    return dst


def _render_live_transcript(stem: str, call: dict) -> str:
    art = call.get("artifact") or {}
    out = [
        f"# {stem} — live transcript (Vapi inbound line)",
        "",
        "AGENT = our receptionist under test (Vapi assistant); CALLER = whoever dialed the line. Times are Vapi's per-message offsets.",
        "",
    ]
    t0 = None
    for m in art.get("messages") or []:
        if m.get("role") not in ("user", "bot"):
            continue
        t = m.get("secondsFromStart")
        if t is None:
            ms = m.get("time")
            if ms is not None:
                t0 = t0 or ms
                t = (ms - t0) / 1000
        ts = f"{int(t) // 60:02d}:{int(t) % 60:02d}" if isinstance(t, int | float) else "--:--"
        who = "AGENT" if m.get("role") == "bot" else "CALLER"
        out.append(f"[{ts}] {who}: {m.get('message', '')}")
    return "\n".join(out) + "\n"


async def fetch(
    settings: Settings, *, limit: int = 5, scenario_id: str | None = None, call_id: str | None = None
) -> list[dict]:
    """Download artifacts for recent inbound calls on the line and write evidence bundles. Returns the metas."""
    settings.require_vapi()
    state = LineState.load(settings)
    client = VapiClient(settings)
    metas: list[dict] = []
    try:
        if call_id:
            calls = [await client.get_call(call_id)]
        else:
            calls = await client.list_calls(phone_number_id=settings.vapi_phone_number_id, limit=limit)
        for call in calls:
            if call.get("type") not in ("inboundPhoneCall", "webCall") or call.get("status") != "ended":
                continue  # webCall = the $0 dashboard "Talk" test of the same assistant
            meta_scn = (
                scenario_id or (call.get("assistant") or {}).get("metadata", {}).get("scenario_id") or state.scenario_id
            )
            target_id = (call.get("assistant") or {}).get("metadata", {}).get("target_id") or state.target_id
            day = (call.get("startedAt") or call.get("createdAt") or "")[:10].replace("-", "")
            stem = f"line-{meta_scn or 'noscn'}-{target_id}-{day}-{call['id'][:6]}"
            meta_path = settings.reports_dir / f"{stem}.meta.json"
            if meta_path.exists():
                metas.append(json.loads(meta_path.read_text()))
                continue
            call = await client.wait_for_artifacts(call["id"], timeout_s=90)
            art = call.get("artifact") or {}
            url = art.get("stereoRecordingUrl") or (art.get("recording") or {}).get("stereoUrl")
            mp3 = None
            if url:
                raw = await client.download(url, settings.recordings_dir / "raw" / f"{stem}.vapi-stereo.mp3")
                mp3 = _swap_channels(raw, settings.recordings_dir / f"{stem}.mp3")
            settings.transcripts_dir.mkdir(parents=True, exist_ok=True)
            (settings.transcripts_dir / f"{stem}.md").write_text(_render_live_transcript(stem, call))
            (settings.transcripts_dir / f"{stem}.json").write_text(json.dumps(call, indent=2, ensure_ascii=False))
            meta = {
                "stem": stem,
                "kind": "inbound-line" if call.get("type") == "inboundPhoneCall" else "web-test",
                "scenario_id": meta_scn,
                "target_id": target_id,
                "title": f"inbound call to the line ({target_id})",
                "call_id": call.get("id"),
                "started_at": call.get("startedAt"),
                "ended_at": call.get("endedAt"),
                "ended_reason": call.get("endedReason"),
                "from": (call.get("customer") or {}).get("number"),
                "to": state.number,
                "cost_usd": call.get("cost"),
                "performance_metrics": art.get("performanceMetrics"),
                "channels": {"left": "AGENT (our receptionist)", "right": "CALLER", "swapped_from_vapi": True},
                "files": {
                    "recording_mp3": str(mp3.relative_to(settings.repo_root)) if mp3 else None,
                    "transcript_md": f"transcripts/{stem}.md",
                    "call_json": f"transcripts/{stem}.json",
                    "events_jsonl": f"reports/events/{call.get('id')}.jsonl",
                },
                "audio": probe_audio(mp3) if mp3 else {"error": "no recording"},
            }
            meta_path.write_text(json.dumps(meta, indent=2))
            metas.append(meta)
    finally:
        await client.aclose()
    return metas


async def up(settings: Settings, target: Target, *, scenario_id: str = "", greeting: str | None = None) -> None:
    """Server + tunnel + arm; block until Ctrl-C. Prints the number to call."""
    import uvicorn

    from .cli import _start_tunnel, _wait_healthy
    from .server import create_app

    if scenario_id:
        find_scenario(settings.scenarios_dir, scenario_id)  # validate early
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host=settings.brain_host, port=settings.brain_port, log_level="warning")
    )
    server_task = asyncio.create_task(server.serve())
    proc, url = await _start_tunnel(settings.brain_port)
    print(f"● tunnel up: {url}")
    try:
        await _wait_healthy(url)
        state = await arm(with_public_url(settings, url), target, scenario_id=scenario_id, greeting=greeting)
        print(
            f"● line armed: {state.number or '(number)'} → assistant {LINE_ASSISTANT_NAME} ({state.assistant_id[:8]}…) as target '{target.id}'"
        )
        print(f"  greeting: {state.greeting}")
        print(
            "  test for $0: Vapi dashboard → Assistants → voxprobe-line → Talk.  Ctrl-C to stop (the number keeps the assistant; tunnel dies)."
        )
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        proc.terminate()
        server.should_exit = True
        await server_task


def main_up(settings: Settings, target_id: str, scenario: str | None, greeting: str | None) -> None:
    target = find_target(settings.targets_dir, target_id)
    sid = find_scenario(settings.scenarios_dir, scenario).id if scenario else ""
    try:
        asyncio.run(up(settings, target, scenario_id=sid, greeting=greeting))
    except KeyboardInterrupt:
        print("● line stopped")
