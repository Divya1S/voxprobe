"""CALL-E adapter: task/schema composition and the dial guard, without touching the network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from voxprobe import calle_client
from voxprobe.config import Settings, TargetNumberError
from voxprobe.scenarios import find_scenario

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def scenario():
    return find_scenario(ROOT / "scenarios", "02")


def test_task_carries_persona_objective_facts_and_boundaries(scenario):
    task = calle_client.build_task(scenario, "Sunrise Orthopedics")
    assert scenario.patient.name in task
    assert scenario.objective in task
    assert scenario.patient.dob_spoken in task
    for fact in scenario.patient.facts_known:
        assert fact in task
    assert "do NOT invent" in task
    assert "an existing appointment" in task  # default boundary
    assert "Sunrise Orthopedics" in task
    assert len(task) < 3500  # a task, not an essay


def test_result_schema_mirrors_success_criteria_and_is_calle_safe(scenario):
    schema = calle_client.build_result_schema(scenario)
    dumped = json.dumps(schema)
    for banned in ("$ref", "oneOf", "anyOf", "allOf"):
        assert banned not in dumped
    crit = schema["properties"]["criteria"]["properties"]
    assert len(crit) == len(scenario.success_criteria)
    assert set(schema["properties"]["criteria"]["required"]) == set(crit)
    for key, spec in crit.items():
        assert key.startswith("c")
        assert spec["enum"] == ["met", "not_met", "unknown"]
        assert spec["description"] in scenario.success_criteria
    assert schema["properties"]["goal_achieved"]["enum"] == ["yes", "partially", "no", "unknown"]


def test_dry_run_has_no_side_effects_and_normalizes_number(scenario):
    out = calle_client.dry_run(scenario, "+1 (415) 555-0100", "Sunrise Orthopedics")
    assert out["recipients"] == [{"phones": ["+14155550100"], "region": "US", "locale": "en-US"}]
    assert out["metadata"] == {"voxprobe_scenario": scenario.id}
    assert out["task"].startswith("You are ")


def test_run_refuses_numbers_off_the_allow_list(scenario, tmp_path):
    settings = Settings(
        calle_api_key="iams_live_dummy", allowed_numbers=frozenset({"+14155550100"}), repo_root=tmp_path
    )
    with pytest.raises(TargetNumberError, match="Refusing to dial"):
        calle_client.run(settings, scenario, "+14155550199", "Sunrise Orthopedics")


def test_run_requires_key(scenario, tmp_path):
    settings = Settings(allowed_numbers=frozenset({"+14155550100"}), repo_root=tmp_path)
    with pytest.raises(RuntimeError, match="CALLE_API_KEY"):
        calle_client.run(settings, scenario, "+14155550100", "Sunrise Orthopedics")


def test_transcript_rendering_labels_sides_and_flags_source():
    task = {
        "status": "completed",
        "task_completed": True,
        "completion_confidence": {"score": 0.9, "label": "high"},
        "summary": "Booked.",
        "evidence": ["..."],
        "structured_result": {"goal_achieved": "yes"},
        "recipients": [
            {
                "attempts": [
                    {
                        "id": "att_1",
                        "status": "completed",
                        "started_at": "t0",
                        "completed_at": "t1",
                        "transcript_turns": [
                            {"offset_seconds": 0, "speaker": "user", "text": "Sunrise Orthopedics, how can I help?"},
                            {"offset_seconds": 3, "speaker": "bot", "text": "Hi, I'm Daniel Reyes, a new patient."},
                            {"offset_seconds": None, "speaker": "unknown", "text": "..."},
                        ],
                    }
                ]
            }
        ],
    }
    md = calle_client.render_transcript_md(task, "calle-02-x")
    assert "[00:00] AGENT: Sunrise" in md
    assert "[00:03] CALLER(CALL-E): Hi, I'm Daniel" in md
    assert "[--:--] UNKNOWN" in md
    assert "integer-second offsets" in md
