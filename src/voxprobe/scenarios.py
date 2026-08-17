"""Scenario schema and loader.

A scenario is a YAML file describing one test call: who the patient is, what they know, what they
want, how they talk, what they must never invent, and how the call should be steered. Scenarios are
data so a reviewer can read them without reading code, and so each recorded call maps 1:1 to a file.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

# Boundaries that apply to EVERY patient regardless of scenario. Scenario-specific ones are added on top.
DEFAULT_MUST_NOT_INVENT = [
    "medical history, meds, allergies or symptoms beyond those listed",
    "an existing appointment, confirmation number or prior visit unless listed",
    "insurance IDs or policy details unless listed",
    "the practice's hours, policies, doctors or prices — ask, don't assert",
    "a callback number — say the number you're calling from is fine",
]


class Patient(BaseModel):
    name: str
    dob: date = Field(description="ISO date, e.g. 1991-03-12 (YAML parses it into a date)")
    dob_spoken: str = Field(description="How the patient says it aloud, e.g. 'March twelfth, nineteen ninety-one'")
    reason: str = Field(description="Why they are calling, in the patient's own words")
    new_patient: bool = True
    facts_known: list[str] = Field(default_factory=list, description="Things the patient may share if asked")
    must_not_invent: list[str] = Field(default_factory=list, description="Scenario-specific boundaries")
    style: str = Field(default="friendly, plain-spoken, a little busy")
    voice_id: str = Field(default="thalia", description="Deepgram Aura-2 voice id (e.g. thalia, luna, orion, apollo)")


class Phase(BaseModel):
    key: str
    goal: str = Field(description="What the patient is trying to accomplish in this phase")
    done_when: str = Field(default="", description="Signal that lets the director advance to the next phase")


class Scenario(BaseModel):
    id: str = Field(pattern=r"^\d{2}-[a-z0-9-]+$", description="e.g. 01-schedule-new-patient")
    title: str
    category: Literal[
        "scheduling", "rescheduling", "cancellation", "refill", "information", "ambiguous", "edge-case", "adversarial"
    ]
    capability_tested: str
    patient: Patient
    objective: str = Field(description="One-sentence outcome the patient wants from this call")
    phases: list[Phase] = Field(min_length=1)
    success_criteria: list[str] = Field(default_factory=list)
    bug_hypotheses: list[str] = Field(default_factory=list, description="What we suspect the agent may get wrong")
    barge_in: bool = Field(default=False, description="True only for scenarios that intentionally interrupt the agent")
    max_turns: int = Field(default=30, ge=4, le=80, description="Safety cap on patient turns")
    max_duration_seconds: int = Field(default=240, ge=60, le=600, description="Safety cap on call length")

    @field_validator("phases")
    @classmethod
    def _unique_phase_keys(cls, phases: list[Phase]) -> list[Phase]:
        keys = [p.key for p in phases]
        if len(keys) != len(set(keys)):
            raise ValueError(f"duplicate phase keys: {keys}")
        return phases

    @property
    def number(self) -> str:
        """'01' from '01-schedule-new-patient' — used in artifact file names."""
        return self.id.split("-", 1)[0]

    @property
    def all_boundaries(self) -> list[str]:
        return DEFAULT_MUST_NOT_INVENT + self.patient.must_not_invent


def load_scenario(path: Path) -> Scenario:
    with path.open() as f:
        data = yaml.safe_load(f)
    return Scenario.model_validate(data)


def load_all_scenarios(directory: Path) -> list[Scenario]:
    scenarios = [load_scenario(p) for p in sorted(directory.glob("*.yaml"))]
    ids = [s.id for s in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate scenario ids in {directory}: {ids}")
    return scenarios


def find_scenario(directory: Path, key: str) -> Scenario:
    """Find by full id ('03-reschedule-existing') or by number ('03')."""
    for s in load_all_scenarios(directory):
        if s.id == key or s.number == key.zfill(2):
            return s
    raise FileNotFoundError(f"no scenario matching {key!r} in {directory}")
