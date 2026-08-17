"""Turn-taking and latency metrics for BOTH parties, computed from the audio-derived transcript.

From the merged, timestamped segments (AGENT / PATIENT) we derive:
* patient response latency = gap from the agent's last word to the patient's first word (our bot's speed — this is
  what a reviewer *hears* as "natural" or "laggy");
* agent response latency = the mirror image (the target agent — a quality signal for the bug report);
* overlaps (negative gaps = someone spoke over the other), long silences, talk share, turn counts.
Vapi's own `performanceMetrics` (per-turn model/voice/transcriber/endpointing latency) and our brain-turn events
(LLM latency, provider, prompt tokens) are attached when available so numbers can be cross-checked.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path


def _turns(segments: list[dict]) -> list[dict]:
    """Collapse consecutive same-speaker segments into turns with start/end/text."""
    turns: list[dict] = []
    for s in segments:
        if turns and turns[-1]["speaker"] == s["speaker"] and s["start"] - turns[-1]["end"] < 1.5:
            turns[-1]["end"] = max(turns[-1]["end"], s["end"])
            turns[-1]["text"] += " " + s["text"]
        else:
            turns.append({"speaker": s["speaker"], "start": s["start"], "end": s["end"], "text": s["text"]})
    return turns


def compute(segments: list[dict], events: list[dict] | None = None, vapi_perf: dict | None = None) -> dict:
    turns = _turns(segments)
    patient_gaps, agent_gaps, overlaps, silences = [], [], [], []
    for prev, nxt in zip(turns, turns[1:], strict=False):
        gap = nxt["start"] - prev["end"]
        if prev["speaker"] != nxt["speaker"]:
            (patient_gaps if nxt["speaker"] == "PATIENT" else agent_gaps).append(round(gap, 2))
        if gap < -0.3:
            overlaps.append({"at": round(nxt["start"], 1), "who_started": nxt["speaker"], "overlap_s": round(-gap, 2)})
        if gap > 2.5:
            silences.append({"after": prev["speaker"], "at": round(prev["end"], 1), "silence_s": round(gap, 2)})

    def stats(xs: list[float]) -> dict:
        if not xs:
            return {"n": 0}
        return {
            "n": len(xs),
            "median_s": round(statistics.median(xs), 2),
            "p90_s": round(sorted(xs)[int(0.9 * (len(xs) - 1))], 2),
            "max_s": round(max(xs), 2),
            "min_s": round(min(xs), 2),
        }

    talk = {"AGENT": 0.0, "PATIENT": 0.0}
    for t in turns:
        talk[t["speaker"]] += t["end"] - t["start"]
    total = max(1e-6, (turns[-1]["end"] - turns[0]["start"]) if turns else 0)

    out = {
        "turns": {
            "AGENT": sum(t["speaker"] == "AGENT" for t in turns),
            "PATIENT": sum(t["speaker"] == "PATIENT" for t in turns),
        },
        "patient_response_latency": stats(patient_gaps),
        "agent_response_latency": stats(agent_gaps),
        "overlaps": overlaps,
        "long_silences": silences,
        "talk_share": {k: round(v / total, 2) for k, v in talk.items()},
        "duration_s": round(total, 1),
    }
    if events:
        brain = [e for e in events if e.get("type") == "brain-turn"]
        if brain:
            lat = [e["latency_ms"] for e in brain]
            out["brain"] = {
                "turns": len(brain),
                "llm_latency_ms": {"median": int(statistics.median(lat)), "max": max(lat)},
                "providers": sorted({e["provider"] for e in brain}),
                "failovers": sum(1 for e in brain if e.get("failed_over_from")),
                "prompt_tokens": {"first": brain[0].get("prompt_tokens"), "last": brain[-1].get("prompt_tokens")},
            }
        interrupted = [e for e in events if e.get("type") == "user-interrupted"]
        out["vapi_user_interrupted_events"] = len(interrupted)
    if vapi_perf:
        out["vapi_performance_metrics"] = {
            k: vapi_perf.get(k)
            for k in (
                "turnLatencyAverage",
                "modelLatencyAverage",
                "voiceLatencyAverage",
                "transcriberLatencyAverage",
                "endpointingLatencyAverage",
                "numUserInterrupted",
                "numAssistantInterrupted",
            )
            if k in vapi_perf
        }
    return out


def render_md(m: dict) -> str:
    pl, al = m["patient_response_latency"], m["agent_response_latency"]
    lines = [
        "| Metric | Value |",
        "|---|---|",
        f"| Turns (agent / patient) | {m['turns']['AGENT']} / {m['turns']['PATIENT']} |",
        f"| Patient response latency (agent stops → patient starts) | median {pl.get('median_s', '–')} s · p90 {pl.get('p90_s', '–')} s · max {pl.get('max_s', '–')} s |",
        f"| Agent response latency (patient stops → agent starts) | median {al.get('median_s', '–')} s · p90 {al.get('p90_s', '–')} s · max {al.get('max_s', '–')} s |",
        f"| Overlaps (talk-over > 0.3 s) | {len(m['overlaps'])} {m['overlaps'][:3] if m['overlaps'] else ''} |",
        f"| Silences > 2.5 s | {len(m['long_silences'])} {m['long_silences'][:3] if m['long_silences'] else ''} |",
        f"| Talk share agent / patient | {m['talk_share']['AGENT']} / {m['talk_share']['PATIENT']} |",
    ]
    if "brain" in m:
        b = m["brain"]
        lines.append(
            f"| Our LLM latency (server-side) | median {b['llm_latency_ms']['median']} ms · max {b['llm_latency_ms']['max']} ms · providers {b['providers']} · failovers {b['failovers']} |"
        )
    if "vapi_performance_metrics" in m:
        lines.append(f"| Vapi performance metrics (ms) | {m['vapi_performance_metrics']} |")
    return "\n".join(lines) + "\n"


def load_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
