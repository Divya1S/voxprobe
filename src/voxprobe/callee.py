"""Callee personas: a *person* who answers the phone — the other end for tasks that call people.

The receptionist line answers as a business (targets/); a callee persona answers as an individual (callees/): a customer
being asked to confirm an appointment, someone receiving a reminder, a lead being qualified. Decisions are scripted as
verbatim lines so a row's ground truth is exact, and the manifest regex proves the scripted line was actually spoken.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class CalleePersona(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    title: str
    situation: str
    facts: list[str] = Field(default_factory=list)
    decision: list[str] = Field(
        default_factory=list, description="Scripted lines; 'say exactly' makes ground truth exact"
    )
    must_not: list[str] = Field(default_factory=list)
    style: str = "friendly, brief"
    greeting: str = "Hello?"
    manifest_regex: str


def load_callee(path: Path) -> CalleePersona:
    with path.open() as f:
        persona = CalleePersona.model_validate(yaml.safe_load(f))
    if persona.id != path.stem:
        raise ValueError(f"callee id {persona.id!r} != filename stem {path.stem!r}")
    return persona


def find_callee(callees_dir: Path, callee_id: str) -> CalleePersona:
    path = callees_dir / f"{callee_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no callee persona {callee_id!r} in {callees_dir}")
    return load_callee(path)


def callee_prompt(p: CalleePersona) -> str:
    """System prompt for the brain when WE are the person who picked up."""
    lines = [
        f"You are {p.name}, a real person who just answered your phone. Situation: {p.situation.strip()}",
        "Speak naturally in one short sentence or two per turn; no lists. Answer what you are asked; do not volunteer.",
        "What you know: " + "; ".join(p.facts) + ".",
        "Your decisions — follow them exactly, including the quoted sentences, when the moment comes: "
        + " ".join(p.decision),
        "Never: " + "; ".join(p.must_not) + ".",
        f"Manner: {p.style}. If the caller says goodbye, say goodbye and stop.",
    ]
    return "\n".join(lines)
