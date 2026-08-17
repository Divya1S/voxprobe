"""Evidence bundle for one call: consistent names, both-sides transcript, metadata.

Layout (all committed to the repo):
  recordings/call-NN-<scenario>-<YYYYMMDD>-<callid6>.mp3      stereo: LEFT = target agent, RIGHT = our patient
  transcripts/call-NN-<scenario>-<date>-<id>.md              timestamped both-sides transcript (from Vapi artifact)
  transcripts/call-NN-<scenario>-<date>-<id>.json            full Vapi call object (messages, cost, performanceMetrics)
  reports/call-NN-<scenario>-<date>-<id>.meta.json           compact summary used by TEST_RESULTS.md
  reports/events/<callid>.jsonl                               raw webhook + brain-turn events (written live by the server)
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings
from .scenarios import Scenario
from .targets import Target

# Vapi's roles from the assistant's point of view: "user" is the party we called (the target agent),
# "bot" is our assistant (the simulated patient).
ROLE_LABEL = {
    "user": "AGENT  ",
    "bot": "PATIENT",
    "system": "SYSTEM ",
    "tool_calls": "TOOL   ",
    "tool_call_result": "TOOL   ",
}


def artifact_stem(scenario: Scenario, call: dict) -> str:
    started = call.get("startedAt") or call.get("createdAt") or datetime.now(UTC).isoformat()
    day = started[:10].replace("-", "")
    return f"call-{scenario.id}-{day}-{call['id'][:6]}"


def _mmss(seconds: float | None) -> str:
    s = int(seconds or 0)
    return f"{s // 60:02d}:{s % 60:02d}"


def render_transcript_md(scenario: Scenario, target: Target, call: dict, settings: Settings) -> str:
    art = call.get("artifact") or {}
    msgs = [m for m in art.get("messages") or [] if m.get("role") in ("user", "bot")]
    started, ended = call.get("startedAt"), call.get("endedAt")
    dur = None
    if started and ended:
        dur = (
            datetime.fromisoformat(ended.replace("Z", "+00:00"))
            - datetime.fromisoformat(started.replace("Z", "+00:00"))
        ).total_seconds()
    lines = [
        f"# {scenario.id} — {scenario.title}",
        "",
        f"- Vapi call id: `{call.get('id')}`",
        f"- Started (UTC): {started}  · Duration: {_mmss(dur)}  · Ended reason: `{call.get('endedReason')}`",
        f"- From (our bot): {settings.caller_number}  → To: {target.name} {(call.get('customer') or {}).get('number')}",
        f"- Patient persona: {scenario.patient.name} · voice: deepgram aura-2/{scenario.patient.voice_id}",
        f"- Objective: {scenario.objective}",
        f"- Cost (USD, Vapi wallet): {call.get('cost')}",
        "",
        "Timestamps are seconds from call start (Vapi artifact). AGENT = the target agent; PATIENT = our simulated caller.",
        "",
    ]
    for m in msgs:
        t = m.get("secondsFromStart")
        text = (m.get("message") or "").strip()
        lines.append(f"[{_mmss(t)}] {ROLE_LABEL.get(m['role'], m['role'])}: {text}")
    return "\n".join(lines) + "\n"


def probe_audio(path: Path) -> dict:
    """ffprobe: channels, sample rate, duration — to verify we really have both sides."""
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=channels,sample_rate,codec_name:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        data = json.loads(out)
        st = (data.get("streams") or [{}])[0]
        return {
            "channels": st.get("channels"),
            "sample_rate": st.get("sample_rate"),
            "codec": st.get("codec_name"),
            "duration_s": float((data.get("format") or {}).get("duration") or 0),
        }
    except Exception as e:  # ffprobe missing or unreadable file — report, don't crash the run
        return {"error": str(e)}


def write_bundle(
    settings: Settings,
    scenario: Scenario,
    target: Target,
    call: dict,
    mp3_path: Path | None,
    mono_paths: dict[str, Path] | None = None,
) -> dict:
    stem = artifact_stem(scenario, call)
    settings.transcripts_dir.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)

    md_path = settings.transcripts_dir / f"{stem}.md"
    md_path.write_text(render_transcript_md(scenario, target, call, settings))
    json_path = settings.transcripts_dir / f"{stem}.json"
    json_path.write_text(json.dumps(call, indent=2, ensure_ascii=False))

    audio = probe_audio(mp3_path) if mp3_path else {"error": "no recording downloaded"}
    art = call.get("artifact") or {}
    meta = {
        "stem": stem,
        "scenario_id": scenario.id,
        "target_id": target.id,
        "title": scenario.title,
        "call_id": call.get("id"),
        "started_at": call.get("startedAt"),
        "ended_at": call.get("endedAt"),
        "ended_reason": call.get("endedReason"),
        "from": settings.caller_number,
        "to": (call.get("customer") or {}).get("number"),
        "cost_usd": call.get("cost"),
        "cost_breakdown": call.get("costBreakdown"),
        "performance_metrics": art.get("performanceMetrics"),
        "num_messages": len([m for m in art.get("messages") or [] if m.get("role") in ("user", "bot")]),
        "files": {
            "recording_mp3": str(mp3_path.relative_to(settings.repo_root)) if mp3_path else None,
            "mono": {k: str(v.relative_to(settings.repo_root)) for k, v in (mono_paths or {}).items()},
            "transcript_md": str(md_path.relative_to(settings.repo_root)),
            "call_json": str(json_path.relative_to(settings.repo_root)),
            "events_jsonl": f"reports/events/{call.get('id')}.jsonl",
        },
        "audio": audio,
    }
    meta_path = settings.reports_dir / f"{stem}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    meta["files"]["meta_json"] = str(meta_path.relative_to(settings.repo_root))
    return meta
