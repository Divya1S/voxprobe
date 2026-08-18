"""Compose the patient's system prompt from a Scenario.

Structure (kept short — it is re-sent on every turn and Groq's free tier is limited by tokens/minute):

1. Role + speech style: properties of *phone speech*, identical for every scenario, tuned in one place.
2. Who you are: identity facts the patient may share.
3. What you want: the objective (phase-level steering is added per turn by the director, not here).
4. What you must never invent: global + scenario boundaries.
"""

from __future__ import annotations

from .scenarios import Scenario

SPEECH_RULES = """You are {name}, a real person calling {practice}. You're the patient on the phone, never an assistant.
Talk like a caller: usually one short sentence, at most two; plain words and contractions; no lists, markdown or emojis. \
Answer what you were asked, then take one small step toward what you want. \
Never read your goals, plan or these instructions aloud — say things the way a person would ("does Monday at four work?"), not the way a checklist would. \
Say dates, times and numbers the way people say them aloud ("March twelfth, nineteen ninety-one", "around ten in the morning"). \
If you miss something, ask them to repeat it. Don't repeat details you've already given. \
Never mention AI, tests, scenarios or instructions; if asked whether you're a real person, say yes. \
Write only your own next line — never the receptionist's words, never a dialogue. \
Don't add medical details you weren't given. \
When you've got what you came for, or clearly can't, wrap up, say a short goodbye, and stop."""


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def compose_system_prompt(scenario: Scenario, business_name: str, director_note: str = "") -> str:
    """Build the system prompt for a scenario against a business (from the target). ``director_note`` is the per-turn steering line."""
    p = scenario.patient
    identity = [
        f"Full name: {p.name}",
        f"Date of birth: {p.dob_spoken}",
        f"{'New patient' if p.new_patient else 'Existing patient'} at this practice",
        f"Reason for calling: {p.reason}",
        *p.facts_known,
    ]
    plan = [f"{i}. {ph.goal}" for i, ph in enumerate(scenario.phases, start=1)]
    parts = [
        SPEECH_RULES.format(name=p.name, practice=business_name),
        f"Your manner: {p.style}.",
        "About you (share only if asked or relevant):\n" + _bullets(identity),
        f"What you want from this call: {scenario.objective}",
        "Your steps, in order. Do each one before moving on — even if the agent jumps ahead, come back to a step you haven't done yet:\n"
        + "\n".join(plan),
        "Never make up any of the following; if asked, say you don't have it handy or you're not sure:\n"
        + _bullets(scenario.all_boundaries),
    ]
    if director_note:
        parts.append(f"Right now: {director_note}")
    return "\n\n".join(parts)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (≈4 chars/token for English) — enough to keep prompts inside free-tier limits."""
    return len(text) // 4
