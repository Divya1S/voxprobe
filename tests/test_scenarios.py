from pathlib import Path

import pytest

from voxprobe.persona import compose_system_prompt, estimate_tokens
from voxprobe.scenarios import DEFAULT_MUST_NOT_INVENT, find_scenario, load_all_scenarios
from voxprobe.targets import find_target, load_all_targets

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = ROOT / "scenarios"
TARGETS_DIR = ROOT / "targets"
BUSINESS = "Sunrise Orthopedics"


def test_all_scenarios_load_and_have_unique_ids():
    scenarios = load_all_scenarios(SCENARIOS_DIR)
    assert len(scenarios) >= 3
    assert len({s.id for s in scenarios}) == len(scenarios)


def test_find_by_number_and_by_id():
    by_number = find_scenario(SCENARIOS_DIR, "1")
    by_id = find_scenario(SCENARIOS_DIR, "01-schedule-new-patient")
    assert by_number.id == by_id.id == "01-schedule-new-patient"


@pytest.mark.parametrize("scenario", load_all_scenarios(SCENARIOS_DIR), ids=lambda s: s.id)
def test_prompt_contains_facts_and_boundaries_and_stays_small(scenario):
    prompt = compose_system_prompt(scenario, BUSINESS)
    p = scenario.patient
    # identity and every shareable fact must be present verbatim
    for needle in [p.name, p.dob_spoken, p.reason, *p.facts_known]:
        assert needle in prompt
    # every boundary (global + scenario) must be present
    for boundary in DEFAULT_MUST_NOT_INVENT + p.must_not_invent:
        assert boundary in prompt
    # the objective must be present
    assert scenario.objective in prompt
    assert BUSINESS in prompt
    # phone-speech rules present, and no assistant-y artifacts
    assert "usually one short sentence" in prompt
    assert "```" not in prompt
    # budget: re-sent every turn on a tokens-per-minute-limited free tier
    assert estimate_tokens(prompt) <= 700, f"prompt too long: ~{estimate_tokens(prompt)} tokens"


def test_prompt_never_leaks_iso_dob():
    """The patient should SAY the date, never read an ISO string like 1991-03-12 aloud."""
    for s in load_all_scenarios(SCENARIOS_DIR):
        assert s.patient.dob.isoformat() not in compose_system_prompt(s, BUSINESS)


def test_targets_load_and_local_clinic_has_ground_truth():
    targets = load_all_targets(TARGETS_DIR)
    assert {t.id for t in targets} >= {"local-clinic", "example-phone-vapi"}
    local = find_target(TARGETS_DIR, "local-clinic")
    assert local.kind == "local"
    gt = local.business.as_ground_truth()
    assert "Monday" in gt and "Doctor Emily Chen" in gt
    phone = find_target(TARGETS_DIR, "example-phone-vapi")
    assert phone.kind == "vapi" and phone.connection.phone_number.startswith("+")
