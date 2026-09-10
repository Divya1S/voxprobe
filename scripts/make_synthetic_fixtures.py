"""Synthetic fixture rows for otherend — no phone call, no CALL-E, no platform identifiers.

Fallback for repositories whose privacy rule forbids any real-call text: the same scenario, profiles and grader, but the
conversation is voxprobe's in-process text simulation (an open model plays the caller, our sample receptionist answers) and
the "self-report" is an open model filling the SAME result_schema from that transcript. Every artifact says SYNTHETIC.
Output: reports/synthetic/<stem>.{calle.json,calle.md,line.md,meta.json,grade.json}.

Usage: uv run python scripts/make_synthetic_fixtures.py [--profiles cooperative,...] [--callees kay2-amelia-confirms,...]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from openai import AsyncOpenAI

from voxprobe import calle_client
from voxprobe.brain import Brain, build_providers
from voxprobe.callee import callee_prompt, find_callee
from voxprobe.config import load_settings
from voxprobe.otherend import grade, grade_foreign, load_probe, load_profile, render_report_md
from voxprobe.scenarios import find_scenario
from voxprobe.simulate import GEMINI_BASE_URL, run_text_simulation
from voxprobe.targets import find_target

SYNTH_NOTE = (
    "SYNTHETIC — in-process text simulation; no phone call, no CALL-E, no platform identifiers. Names are fictional."
)


def _turns(transcript: list[dict]) -> list[dict]:
    """voxprobe transcript -> CallTask-shaped transcript_turns (bot = caller, user = the line); degenerate turns dropped."""
    transcript = [t for t in transcript if re.search(r"[A-Za-z0-9]", t.get("text") or "")]
    return [
        {"offset_seconds": int(t["t"]), "speaker": "bot" if t["speaker"] == "CALLER" else "user", "text": t["text"]}
        for t in transcript
    ]


def _line_md(stem: str, transcript: list[dict]) -> str:
    out = [
        f"# {stem} — line transcript ({SYNTH_NOTE})",
        "",
        "AGENT = our side of the line (receptionist or persona); CALLER = the simulated caller.",
        "",
    ]
    for t in transcript:
        who = "AGENT" if t["speaker"] == "AGENT" else "CALLER"
        s = int(t["t"])
        out.append(f"[{s // 60:02d}:{s % 60:02d}] {who}: {t['text']}")
    return "\n".join(out) + "\n"


async def _self_report(settings, task_text: str, schema: dict, transcript: list[dict]) -> dict:
    """An open model fills the result_schema from the transcript — the synthetic stand-in for a caller's structured_result."""
    client = AsyncOpenAI(base_url=GEMINI_BASE_URL, api_key=settings.google_api_key, timeout=60, max_retries=3)
    convo = "\n".join(f"{'CALLER' if t['speaker'] == 'CALLER' else 'OTHER SIDE'}: {t['text']}" for t in transcript)
    prompt = (
        "You placed the phone call below on behalf of the task. Fill the JSON schema strictly from what was actually said; "
        "use 'unknown'/empty values when the call did not establish something. Also give task_completed (true/false) and "
        "confidence (0-1) for how well the report matches the transcript. Return ONLY a JSON object with keys "
        "structured_result, task_completed, confidence.\n\nTASK:\n"
        + task_text
        + "\n\nSCHEMA:\n"
        + json.dumps(schema)
        + "\n\nCALL:\n"
        + convo
    )
    for model in ("gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.1-flash-lite"):
        try:
            r = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=800,
                temperature=0.2,
            )
            return json.loads(r.choices[0].message.content)
        except Exception as e:  # noqa: BLE001 - try the next free model
            last = e
    raise RuntimeError(f"self-report failed on every model: {last}")


def _call_task(stem: str, transcript: list[dict], report: dict, summary: str) -> dict:
    conf = float(report.get("confidence") or 0.0)
    return {
        "stem": stem,
        "object": "call",
        "status": "completed",
        "synthetic": SYNTH_NOTE,
        "task_completed": bool(report.get("task_completed")),
        "completion_confidence": {
            "score": round(conf, 2),
            "label": "high" if conf >= 0.75 else "medium" if conf >= 0.5 else "low",
        },
        "summary": summary,
        "evidence": [],
        "structured_result": report.get("structured_result") or {},
        "recipients": [
            {
                "status": "completed",
                "structured_result": report.get("structured_result") or {},
                "attempts": [{"status": "completed", "transcript_turns": _turns(transcript)}],
            }
        ],
    }


async def receptionist_row(settings, profile_id: str, probe_id: str, out: Path) -> dict:
    profile = load_profile(settings.profiles_dir / f"{profile_id}.yaml")
    probe = load_probe(settings.probes_dir / f"{probe_id}.yaml", settings.scenarios_dir)
    scenario = find_scenario(settings.scenarios_dir, probe.scenario_id)
    target = find_target(settings.targets_dir, profile.target_id)
    sim = await run_text_simulation(settings, scenario, target, quiet=True, judge=False, turn_pace_s=4.0)
    transcript = sim["transcript"]
    if profile.greeting:  # the profile's greeting is the receptionist's first line on the live line; mirror it
        transcript[0] = {**transcript[0], "text": profile.greeting.strip()}
    task_text = calle_client.build_task(scenario, target.business.name)
    schema = calle_client.build_result_schema(scenario)
    report = await _self_report(settings, task_text, schema, transcript)
    stem = f"synth-{probe.id}-{profile.id}-{datetime.now(UTC).strftime('%Y%m%d')}"
    task = _call_task(
        stem,
        transcript,
        report,
        f"{SYNTH_NOTE} Simulated caller for scenario {scenario.id} against profile {profile.id}.",
    )
    meta = {
        "stem": f"line-{stem}",
        "kind": "synthetic",
        "scenario_id": scenario.id,
        "target_id": profile.target_id,
        "note": SYNTH_NOTE,
    }
    line_md = _line_md(meta["stem"], transcript)
    g = grade(task, profile, probe, meta, line_md)
    _write(out, stem, task, task_text, schema, line_md, meta, g)
    return g.model_dump()


async def callee_row(settings, callee_id: str, probe_id: str, out: Path) -> dict:
    persona = find_callee(settings.repo_root / "callees", callee_id)
    probe = load_probe(settings.probes_dir / f"{probe_id}.yaml", settings.scenarios_dir)
    brain = Brain(build_providers(settings))
    caller_sys = (
        probe.task_text + "\nYou are on the phone. Speak one or two short sentences per turn. When done, say goodbye."
    )
    transcript: list[dict] = [{"t": 0.0, "speaker": "AGENT", "text": persona.greeting}]
    hist_caller: list[dict] = [{"role": "user", "content": persona.greeting}]  # caller sees the persona as "user"
    hist_callee: list[dict] = [{"role": "assistant", "content": persona.greeting}]
    t = 0.0
    for _ in range(8):
        rec = await brain.reply(caller_sys, hist_caller)
        t += 6
        transcript.append({"t": t, "speaker": "CALLER", "text": rec.reply})
        hist_caller.append({"role": "assistant", "content": rec.reply})
        hist_callee.append({"role": "user", "content": rec.reply})
        if re.search(r"\b(goodbye|bye)\b", rec.reply, re.I):
            break
        rec2 = await brain.reply(callee_prompt(persona), hist_callee)
        t += 5
        transcript.append({"t": t, "speaker": "AGENT", "text": rec2.reply})
        hist_callee.append({"role": "assistant", "content": rec2.reply})
        hist_caller.append({"role": "user", "content": rec2.reply})
        if re.search(r"\b(goodbye|bye)\b", rec2.reply, re.I):
            break
        await asyncio.sleep(4.0)
    report = await _self_report(settings, probe.task_text, probe.result_schema, transcript)
    stem = f"synth-{probe.id}-{persona.id}-{datetime.now(UTC).strftime('%Y%m%d')}"
    task = _call_task(
        stem, transcript, report, f"{SYNTH_NOTE} Simulated caller running a foreign task against persona {persona.id}."
    )
    meta = {
        "stem": f"line-{stem}",
        "kind": "synthetic",
        "scenario_id": probe.id,
        "target_id": f"callee:{persona.id}",
        "note": SYNTH_NOTE,
    }
    line_md = _line_md(meta["stem"], transcript)
    g = grade_foreign(task, persona.id, persona.manifest_regex, probe, meta, line_md)
    _write(out, stem, task, probe.task_text, probe.result_schema, line_md, meta, g)
    return g.model_dump()


def _write(out: Path, stem: str, task: dict, task_text: str, schema: dict, line_md: str, meta: dict, g) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.calle.json").write_text(
        json.dumps(
            {
                "stem": stem,
                "scenario": meta["scenario_id"],
                "synthetic": SYNTH_NOTE,
                "request": {
                    "task": task_text,
                    "recipients": [{"phones": ["+12025550100"], "region": "US", "locale": "en-US"}],
                    "result_schema": schema,
                },
                "task": task,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    (out / f"{stem}.calle.md").write_text(
        calle_client.render_transcript_md(task, stem).replace("CALL-E live transcript", f"transcript ({SYNTH_NOTE})")
    )
    (out / f"{meta['stem']}.md").write_text(line_md)
    (out / f"{meta['stem']}.meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    (out / f"{stem}.grade.json").write_text(json.dumps(g.model_dump(), indent=2, ensure_ascii=False) + "\n")
    fails = [c.check for c in g.checks if c.verdict == "fail"]
    print(
        f"● {stem}: overall {g.overall.upper()} usable={g.usable}" + (f" failing={fails}" if fails else ""), flush=True
    )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", default="")
    ap.add_argument("--callees", default="")
    ap.add_argument("--probe", default="02-constraints")
    ap.add_argument("--foreign-probe", default="foreign-appointment-confirm")
    args = ap.parse_args()
    settings = load_settings()
    out = settings.reports_dir / "synthetic"
    grades = []
    for pid in [p for p in args.profiles.split(",") if p]:
        grades.append(await receptionist_row(settings, pid, args.probe, out))
    for cid in [c for c in args.callees.split(",") if c]:
        grades.append(await callee_row(settings, cid, args.foreign_probe, out))
    if grades:
        from voxprobe.otherend import GradeReport

        (out / "REPORT.md").write_text(
            render_report_md(
                [GradeReport.model_validate(json.loads(p.read_text())) for p in sorted(out.glob("*.grade.json"))]
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
