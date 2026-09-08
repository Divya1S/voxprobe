"""Foreign probes (another author's task text + schema, verbatim) graded per callee persona with field regexes."""

from __future__ import annotations

from pathlib import Path

from voxprobe.callee import find_callee
from voxprobe.otherend import grade_foreign, load_probe

ROOT = Path(__file__).resolve().parents[1]


def _task(structured: dict, turns: list[tuple[str, str]], score: float) -> dict:
    return {
        "stem": "calle-foreign-test",
        "status": "completed",
        "task_completed": True,
        "completion_confidence": {"score": score, "label": "high"},
        "structured_result": structured,
        "recipients": [
            {
                "attempts": [
                    {
                        "transcript_turns": [
                            {"offset_seconds": i, "speaker": s, "text": t} for i, (s, t) in enumerate(turns)
                        ]
                    }
                ]
            }
        ],
    }


def test_foreign_probe_loads_with_verbatim_task_and_schema():
    probe = load_probe(ROOT / "probes" / "foreign-appointment-confirm.yaml", ROOT / "scenarios")
    assert probe.kind == "foreign"
    assert "KAY2 Studios" in probe.task_text and "can_attend" in probe.result_schema["properties"]
    assert set(probe.expectations) == {"kay2-amelia-confirms", "kay2-amelia-reschedules", "kay2-amelia-ambiguous"}


def test_reschedule_row_passes_when_report_matches_the_scripted_decision():
    probe = load_probe(ROOT / "probes" / "foreign-appointment-confirm.yaml", ROOT / "scenarios")
    persona = find_callee(ROOT / "callees", "kay2-amelia-reschedules")
    transcript = "[00:01] AGENT: Hello, Amelia speaking.\n[00:20] AGENT: No, I can't make the third anymore, sorry.\n[00:40] AGENT: Friday the fourth at ten works for me.\n"
    task = _task(
        {
            "can_attend": "no",
            "confirmed_time": "",
            "requested_time": "2026-09-04T10:00:00+01:00",
            "disposition": "reschedule_requested",
        },
        [("bot", "Is this Amelia?"), ("user", "Yes, this is Amelia"), ("bot", "Can you attend on the third at ten?")],
        0.9,
    )
    r = grade_foreign(
        task, persona.id, persona.manifest_regex, probe, {"stem": "line-x", "target_id": "callee:x"}, transcript
    )
    assert r.usable and r.overall == "pass", [(c.check, c.verdict, c.got) for c in r.checks]


def test_ambiguity_reported_as_yes_fails_and_calibration_flags_it():
    probe = load_probe(ROOT / "probes" / "foreign-appointment-confirm.yaml", ROOT / "scenarios")
    persona = find_callee(ROOT / "callees", "kay2-amelia-ambiguous")
    transcript = (
        "[00:01] AGENT: Hi, this is Amelia.\n[00:15] AGENT: I'm honestly not sure yet, can I let you know later?\n"
    )
    task = _task(
        {
            "can_attend": "yes",
            "confirmed_time": "2026-09-03T10:00:00+01:00",
            "requested_time": "",
            "disposition": "confirmed",
        },
        [("bot", "Can you attend?")],
        0.95,
    )
    r = grade_foreign(task, persona.id, persona.manifest_regex, probe, {"stem": "line-y"}, transcript)
    verdicts = {c.check: c.verdict for c in r.checks}
    assert verdicts["manifest"] == "pass"
    assert verdicts["field.can_attend"] == "fail" and verdicts["field.disposition"] == "fail"
    assert verdicts["confidence_calibration"] == "fail"
    assert r.overall == "fail"


def test_manifest_miss_makes_the_row_unusable():
    probe = load_probe(ROOT / "probes" / "foreign-appointment-confirm.yaml", ROOT / "scenarios")
    persona = find_callee(ROOT / "callees", "kay2-amelia-confirms")
    r = grade_foreign(
        _task({"can_attend": "yes", "confirmed_time": "", "requested_time": "", "disposition": "confirmed"}, [], 0.8),
        persona.id,
        persona.manifest_regex,
        probe,
        {},
        "[00:01] AGENT: Hello?\n",
    )
    assert not r.usable
