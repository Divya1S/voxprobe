"""Turn-taking and latency metrics for BOTH parties, computed from the audio-derived transcript.

Inputs are timestamped speech segments per channel (AGENT / PATIENT) from `retranscribe.py` (timing from each
channel's energy envelope; words from Whisper). We derive:

* **response gaps** — at every speaker change, the gap from the previous speaker's last word to the next speaker's
  first word. Split by direction: `patient_response` (agent stops → patient starts: our simulator's speed, what a
  reviewer hears as natural or laggy) and `agent_response` (patient stops → agent starts: the agent under test).
  Summarised as n / p50 / p95 / max (p95 only when n ≥ 5 — percentiles over four numbers are noise).
* **dead air** — response gaps ≥ DEAD_AIR_S. These ARE part of the response-gap distribution above (not a second
  event); they are listed separately, attributed to the party that was slow, so the judge must weigh them.
* **overlaps** — negative gaps (someone started before the other finished) beyond OVERLAP_S.
* **intra-turn pauses** — long silences WITHIN one speaker's turn (a distinct phenomenon: hesitation / TTS stall).
* talk share, turn counts.

The thresholds are a named *turn-segmentation policy* (SegmentationPolicy) rather than magic numbers.
Pipecat's own metrics (turn latency components) and our brain-turn events are attached when available.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class SegmentationPolicy:
    merge_gap_s: float = 1.5  # same-speaker segments closer than this belong to one turn
    overlap_s: float = 0.3  # a new speaker starting more than this before the other ends = talk-over
    dead_air_s: float = 3.0  # a response gap this long is dead air (industry: >2 s reads as "poor")
    intra_pause_s: float = 2.5  # a pause this long inside one turn is worth listing


DEFAULT_POLICY = SegmentationPolicy()


def _turns(segments: list[dict], policy: SegmentationPolicy) -> list[dict]:
    """Collapse consecutive same-speaker segments into turns; remember internal pauses."""
    turns: list[dict] = []
    for s in segments:
        if turns and turns[-1]["speaker"] == s["speaker"] and s["start"] - turns[-1]["end"] < policy.merge_gap_s:
            pause = s["start"] - turns[-1]["end"]
            if pause > 0:
                turns[-1]["pauses"].append(round(pause, 2))
            turns[-1]["end"] = max(turns[-1]["end"], s["end"])
            turns[-1]["text"] += " " + s["text"]
        else:
            turns.append(
                {"speaker": s["speaker"], "start": s["start"], "end": s["end"], "text": s["text"], "pauses": []}
            )
    return turns


def _summary(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    out = {
        "n": len(xs),
        "p50_s": round(statistics.median(xs), 2),
        "max_s": round(max(xs), 2),
        "min_s": round(min(xs), 2),
    }
    if len(xs) >= 5:
        srt = sorted(xs)
        out["p95_s"] = round(srt[min(len(srt) - 1, int(round(0.95 * (len(srt) - 1))))], 2)
    return out


def compute(
    segments: list[dict],
    events: list[dict] | None = None,
    vapi_perf: dict | None = None,
    policy: SegmentationPolicy = DEFAULT_POLICY,
) -> dict:
    turns = _turns(segments, policy)
    patient_gaps: list[float] = []
    agent_gaps: list[float] = []
    dead_air: list[dict] = []
    overlaps: list[dict] = []
    # Walk turns in start order against the "frontier" = the last moment ANYONE was speaking. A response gap is
    # measured from the frontier, not from the immediately preceding turn, so a short interjection nested inside a
    # long turn (a barge-in, a backchannel) is scored as talk-over — never as fake dead air of the other party.
    frontier = turns[0]["end"] if turns else 0.0
    for prev, nxt in zip(turns, turns[1:], strict=False):
        gap = round(nxt["start"] - frontier, 2)
        talk_over = round(min(frontier, nxt["end"]) - nxt["start"], 2)
        contained = nxt["end"] <= frontier  # wholly inside the other party's turn: an overlap event, not a hand-over
        prev_speaker = prev["speaker"]
        frontier = max(frontier, nxt["end"])
        if prev_speaker == nxt["speaker"]:
            continue  # same speaker back-to-back beyond merge gap: not a response
        if talk_over > policy.overlap_s:
            overlaps.append({"at": round(nxt["start"], 1), "who_started": nxt["speaker"], "overlap_s": talk_over})
        if contained:
            continue
        (patient_gaps if nxt["speaker"] == "PATIENT" else agent_gaps).append(gap)
        if gap >= policy.dead_air_s:
            dead_air.append(
                {"at": round(nxt["start"] - gap, 1), "gap_s": gap, "slow_party": nxt["speaker"], "after": prev_speaker}
            )

    intra_pauses = [
        {"speaker": t["speaker"], "at": round(t["start"], 1), "pause_s": p}
        for t in turns
        for p in t["pauses"]
        if p >= policy.intra_pause_s
    ]

    talk = {"AGENT": 0.0, "PATIENT": 0.0}
    for t in turns:
        talk[t["speaker"]] += t["end"] - t["start"]
    total = max(1e-6, (turns[-1]["end"] - turns[0]["start"]) if turns else 0)

    out = {
        "policy": asdict(policy),
        "turns": {
            "AGENT": sum(t["speaker"] == "AGENT" for t in turns),
            "PATIENT": sum(t["speaker"] == "PATIENT" for t in turns),
        },
        "patient_response": _summary(patient_gaps),
        "agent_response": _summary(agent_gaps),
        "dead_air": dead_air,  # subset of the response gaps above, ≥ policy.dead_air_s
        "overlaps": overlaps,
        "intra_turn_pauses": intra_pauses,
        "talk_share": {k: round(v / total, 2) for k, v in talk.items()},
        "duration_s": round(total, 1),
    }
    if events:
        brain = [e for e in events if e.get("type") == "brain-turn"]
        if brain:
            lat = [e["latency_ms"] for e in brain]
            out["brain"] = {
                "turns": len(brain),
                "llm_latency_ms": {"p50": int(statistics.median(lat)), "max": max(lat)},
                "providers": sorted({e["provider"] for e in brain}),
                "failovers": sum(1 for e in brain if e.get("failed_over_from")),
                "prompt_tokens": {"first": brain[0].get("prompt_tokens"), "last": brain[-1].get("prompt_tokens")},
            }
        interrupted = [e for e in events if e.get("type") == "user-interrupted"]
        if interrupted:
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


def _fmt(s: dict) -> str:
    if not s or s.get("n", 0) == 0:
        return "n=0"
    parts = [f"n={s['n']}", f"p50 {s['p50_s']} s"]
    if "p95_s" in s:
        parts.append(f"p95 {s['p95_s']} s")
    parts.append(f"max {s['max_s']} s")
    return " · ".join(parts)


def render_md(m: dict) -> str:
    lines = [
        "| Metric | Value |",
        "|---|---|",
        f"| Turns (agent / caller) | {m['turns']['AGENT']} / {m['turns']['PATIENT']} |",
        f"| Caller response gap (agent stops → caller starts) | {_fmt(m['patient_response'])} |",
        f"| Agent response gap (caller stops → agent starts) | {_fmt(m['agent_response'])} |",
        f"| Dead air (response gap ≥ {m['policy']['dead_air_s']} s) | {len(m['dead_air'])}"
        + (
            " — " + "; ".join(f"{d['gap_s']} s at {d['at']} s ({d['slow_party']} slow)" for d in m["dead_air"][:4])
            if m["dead_air"]
            else ""
        )
        + " |",
        f"| Overlaps (talk-over > {m['policy']['overlap_s']} s) | {len(m['overlaps'])}"
        + (
            " — " + "; ".join(f"{o['who_started']} +{o['overlap_s']} s at {o['at']} s" for o in m["overlaps"][:4])
            if m["overlaps"]
            else ""
        )
        + " |",
        f"| Intra-turn pauses ≥ {m['policy']['intra_pause_s']} s | {len(m['intra_turn_pauses'])} |",
        f"| Talk share agent / caller | {m['talk_share']['AGENT']} / {m['talk_share']['PATIENT']} |",
    ]
    if "brain" in m:
        b = m["brain"]
        lines.append(
            f"| Caller LLM latency (in-process) | p50 {b['llm_latency_ms']['p50']} ms · max {b['llm_latency_ms']['max']} ms · "
            f"providers {b['providers']} · failovers {b['failovers']} |"
        )
    if "vapi_performance_metrics" in m:
        lines.append(f"| Vapi performance metrics (ms) | {m['vapi_performance_metrics']} |")
    return "\n".join(lines) + "\n"


def load_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
