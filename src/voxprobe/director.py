"""The director: light per-turn steering so the patient stays natural but on task.

The persona prompt already contains the ordered plan (phases). The director adds a one-line note for
*this* turn only: pacing pressure near the turn/time caps, "answer their question first", and
"don't repeat yourself". It never scripts wording — that would make the bot sound like a benchmark
runner, which is exactly what the reviewers penalize.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .scenarios import Scenario

_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", text.strip().lower())


@dataclass
class CallState:
    """Per-call memory the director needs. One instance per live call (keyed by scenario/call id)."""

    scenario: Scenario
    business_name: str = "the office"
    started_at: float = field(default_factory=time.monotonic)
    patient_turns: int = 0
    previous_replies: list[str] = field(default_factory=list)

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at


def director_note(state: CallState, agent_last_utterance: str | None) -> str:
    """Return a short instruction for this turn (may be empty)."""
    s = state.scenario
    notes: list[str] = []

    turns_left = s.max_turns - state.patient_turns
    seconds_left = s.max_duration_seconds - state.elapsed_seconds

    if turns_left <= 3 or seconds_left <= 30:
        notes.append("This must be your last turn: confirm what you have in one sentence and say goodbye.")
    elif turns_left <= 6 or seconds_left <= 60:
        notes.append("Time is nearly up: get to your goal directly and start wrapping up.")

    if agent_last_utterance:
        text = agent_last_utterance.strip()
        if text.endswith("?"):
            notes.append("They asked you a question — answer it directly first.")
        if len(text.split()) > 60:
            notes.append("They said a lot; reply briefly to the part that matters to you.")

    if state.previous_replies:
        last = _norm(state.previous_replies[-1])
        if len(state.previous_replies) >= 2 and _norm(state.previous_replies[-2]) == last:
            notes.append("You've said that twice; don't repeat it — move forward or ask something new.")

    if state.patient_turns == 0:
        notes.append("This is your first line: greet briefly and say why you're calling.")

    return " ".join(notes)


def looks_like_goodbye(reply: str) -> bool:
    r = _norm(reply)
    return bool(re.search(r"\b(bye|goodbye|bye-bye|take care|have a good (day|one))\b", r))
