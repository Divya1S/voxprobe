"""CALL-E adapter: CALL-E's outbound agent as a *caller* that we hand a voxprobe persona and objective to.

CALL-E's Developer API (https://docs.heycall-e.com) is plan-then-dial: one natural-language ``task``, optional JSON
``result_schema``, recipients — no persona field, no voice choice, no custom brain, no mid-call control, no audio via the
API. What comes back is a CallTask: ``status``, ``summary``, ``task_completed``, ``completion_confidence``, ``evidence[]``,
``structured_result`` and, per attempt, ``transcript_turns[]`` with *integer-second* offsets and ``speaker`` bot|user.

voxprobe's job here is narrow and honest:
* compose the task text from a scenario (the same person our text/audio callers play) so the comparison is apples to apples;
* ask CALL-E for a structured result that mirrors the scenario's success criteria (so its self-report can be checked
  against our judge and against the audio recorded on the other end of the line);
* dial only allow-listed numbers; wait; keep the raw CallTask and developer events as evidence.

Nothing here measures timing — CALL-E's offsets are whole seconds and its audio is not exposed by the API. Timing comes
from our side of the line (the agent under test records the call in stereo).
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings, assert_allowed_target, normalize_e164
from .scenarios import Scenario

SCHEMA_KEY_RE = re.compile(r"[^a-z0-9]+")


def _key(text: str, i: int) -> str:
    """Stable, schema-safe key for a success criterion: 'c1_agent_does_not_book'."""
    words = SCHEMA_KEY_RE.sub("_", text.lower()).strip("_").split("_")[:5]
    return f"c{i}_{'_'.join(words)}"


def build_task(scenario: Scenario, business: str = "the office you are calling", *, reveal_test: bool = False) -> str:
    """Render the scenario as CALL-E's natural-language task.

    CALL-E's docs: include the goal, relevant details the voice agent should know, and the exact information to collect.
    The persona's boundaries are passed as hard rules so CALL-E's agent does not invent what our own callers may not.
    """
    p = scenario.patient
    lines = [
        f"You are {p.name}, a {'new' if p.new_patient else 'returning'} patient calling {business}. "
        f"Speak as this person in the first person; never say you are an AI unless asked directly.",
        f"Why you are calling, in your own words: {p.reason}",
        f"Your goal for this call: {scenario.objective}",
        f"Your date of birth, if they ask: {p.dob_spoken} ({p.dob.isoformat()}).",
    ]
    if p.facts_known:
        lines.append("Details you know and may share if asked: " + "; ".join(p.facts_known) + ".")
    lines.append(
        "Hard rules — do NOT invent any of the following; if asked, say you don't know or ask them: "
        + "; ".join(scenario.all_boundaries)
        + "."
    )
    lines.append("Manner: " + p.style + ". Keep each turn short like a real phone call; answer their questions first.")
    plan = " ".join(f"({i}) {ph.goal}" for i, ph in enumerate(scenario.phases, 1))
    lines.append("Rough plan for the conversation: " + plan)
    lines.append(
        "When the call is over, report exactly what the receptionist confirmed (day, time, provider, any policy they "
        "stated), whether each of your requirements was respected, and anything the receptionist got wrong, "
        "contradicted, or refused. Report only what was actually said."
    )
    if reveal_test:
        lines.append("Note: the other side is a test line operated by the same team; this is a QA call.")
    return "\n".join(lines)


def build_result_schema(scenario: Scenario) -> dict[str, Any]:
    """JSON Schema for CALL-E's structured_result (no $ref/oneOf/anyOf/allOf — CALL-E rejects those).

    Mirrors the scenario's success criteria one-to-one so CALL-E's self-report can be compared with our judge's verdicts.
    """
    criteria = {
        _key(c, i): {
            "type": "string",
            "enum": ["met", "not_met", "unknown"],
            "description": c,
        }
        for i, c in enumerate(scenario.success_criteria, 1)
    }
    return {
        "type": "object",
        "required": ["goal_achieved", "outcome_summary", "confirmed", "criteria", "agent_errors"],
        "properties": {
            "goal_achieved": {
                "type": "string",
                "enum": ["yes", "partially", "no", "unknown"],
                "description": f"Was this achieved: {scenario.objective}",
            },
            "outcome_summary": {"type": "string", "description": "One or two sentences: what was agreed or not."},
            "confirmed": {
                "type": "object",
                "description": "What the receptionist explicitly confirmed; empty string when not confirmed.",
                "required": ["day", "time", "provider"],
                "properties": {
                    "day": {"type": "string"},
                    "time": {"type": "string"},
                    "provider": {"type": "string"},
                },
            },
            "criteria": {
                "type": "object",
                "description": "Per-requirement outcome, judged only from what was actually said on the call.",
                "required": list(criteria),
                "properties": criteria,
            },
            "agent_errors": {
                "type": "array",
                "description": "Anything the receptionist said that was wrong, contradictory, unsafe, or a refusal to do an ordinary task. Quote when possible.",
                "items": {"type": "string"},
            },
        },
    }


@dataclass
class CalleRun:
    stem: str
    call_id: str
    task: dict[str, Any]  # raw CallTask
    events: list[dict[str, Any]]
    raw_path: Path
    transcript_path: Path


def _client(settings: Settings):
    settings.require_calle()
    try:
        from calle import CalleClient
    except ImportError as e:  # pragma: no cover - depends on the optional extra
        raise RuntimeError("pip extra missing: uv sync --extra calle") from e
    return CalleClient(api_key=settings.calle_api_key, base_url=settings.calle_base_url)


def probe(settings: Settings) -> dict[str, Any]:
    """Authenticated, read-only check that spends no calls: GET /v1/goals."""
    client = _client(settings)
    try:
        goals = client.goals.list(limit=5)
    finally:
        client.close()
    data = goals.get("data") if isinstance(goals, dict) else None
    return {"ok": True, "base_url": settings.calle_base_url, "goals_visible": len(data or [])}


def dry_run(scenario: Scenario, number: str, business: str) -> dict[str, Any]:
    """What `run` would send — no network. The contributors' guide for awesome-phone-call-agents asks for exactly this."""
    return {
        "task": build_task(scenario, business),
        "recipients": [{"phones": [normalize_e164(number)], "region": "US", "locale": "en-US"}],
        "result_schema": build_result_schema(scenario),
        "metadata": {"voxprobe_scenario": scenario.id},
    }


def _stem(scenario: Scenario) -> str:
    return f"calle-{scenario.id}-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"


def render_transcript_md(task: dict[str, Any], stem: str) -> str:
    """CALL-E's transcript_turns as our transcript format. Offsets are CALL-E's integer seconds — not audio-derived."""
    out = [
        f"# {stem} — CALL-E live transcript",
        "",
        "Source: CALL-E CallTask.transcript_turns (integer-second offsets; words and timing are CALL-E's, not measured from audio).",
        "",
    ]
    for r in task.get("recipients") or []:
        for a in r.get("attempts") or []:
            out.append(
                f"## attempt {a.get('id', '?')} — status {a.get('status')} — {a.get('started_at')} → {a.get('completed_at')}"
            )
            out.append("")
            for t in a.get("transcript_turns") or []:
                off = t.get("offset_seconds")
                ts = f"{int(off) // 60:02d}:{int(off) % 60:02d}" if isinstance(off, int | float) else "--:--"
                who = {"bot": "CALLER(CALL-E)", "user": "AGENT"}.get(t.get("speaker"), "UNKNOWN")
                out.append(f"[{ts}] {who}: {t.get('text', '')}")
            out.append("")
    out += [
        "## CALL-E self-report",
        "",
        f"- status: {task.get('status')}  task_completed: {task.get('task_completed')}  confidence: {task.get('completion_confidence')}",
        f"- summary: {task.get('summary')}",
        "- evidence: " + json.dumps(task.get("evidence"), ensure_ascii=False),
        "- structured_result: " + json.dumps(task.get("structured_result"), ensure_ascii=False),
        "",
    ]
    return "\n".join(out)


def run(
    settings: Settings,
    scenario: Scenario,
    number: str,
    business: str,
    *,
    timeout_s: float = 600.0,
    webhook_url: str | None = None,
) -> CalleRun:
    """Place ONE real CALL-E call. Refuses any number not on ALLOWED_NUMBERS_E164. Keeps raw evidence on disk."""
    number = normalize_e164(number)
    assert_allowed_target(number, settings.allowed_numbers)
    payload = dry_run(scenario, number, business)
    client = _client(settings)
    stem = _stem(scenario)
    try:
        created = client.calls.create(
            task=payload["task"],
            recipients=payload["recipients"],
            result_schema=payload["result_schema"],
            metadata=payload["metadata"],
            webhook_url=webhook_url,
            idempotency_key=stem,
        )
        call_id = created["id"]
        task = client.calls.wait_for_result(call_id, interval_seconds=3.0, timeout_seconds=timeout_s)
        events: list[dict[str, Any]] = []
        cursor = None
        for _ in range(20):
            page = client.calls.list_events(call_id, cursor=cursor, limit=100)
            events.extend(page.get("data") or [])
            cursor = page.get("next_cursor")
            if not cursor:
                break
    finally:
        client.close()
    out_dir = settings.reports_dir / "calle"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"{stem}.calle.json"
    raw_path.write_text(
        json.dumps(
            {
                "stem": stem,
                "scenario": scenario.id,
                "request": payload,
                "created": created,
                "task": task,
                "events": events,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    settings.transcripts_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = settings.transcripts_dir / f"{stem}.calle.md"
    transcript_path.write_text(render_transcript_md(task, stem))
    return CalleRun(stem, call_id, task, events, raw_path, transcript_path)
