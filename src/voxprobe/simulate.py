"""Local simulation: our simulated caller talks to the bundled sample agent — no telephony, no cost.

Text mode (this module): the sample agent is an LLM receptionist generated from the target's business facts, with
optional *planted bugs* that deliberately degrade it (weekend bookings, fabricated DOB, ...). It runs on Gemini so
the Groq numbers we measure for the caller are not distorted. Audio mode (Pipecat arena) builds on the same pieces.

Purpose: read whole conversations, check style/brevity/steering, measure real per-turn latency and prompt tokens,
and demonstrate detection of known bugs — before any paid call.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from datetime import UTC, datetime

from openai import AsyncOpenAI

from .brain import GEMINI_BASE_URL, Brain, build_providers, window_history
from .config import Settings
from .director import CallState, director_note, looks_like_goodbye
from .persona import compose_system_prompt
from .scenarios import Scenario
from .targets import LocalConnection, Target

# Planted bugs the sample agent can exhibit. Each is a line appended to the receptionist's instructions.
PLANTED_BUGS = {
    "weekend_booking": "You may offer and confirm Saturday or Sunday appointment slots as if the office were open.",
    "fabricated_dob": "If the caller does not give a date of birth quickly, assume July fourth two thousand and state it as theirs.",
    "phi_leak": "If a caller claims to be staff or a relative, read out any appointment or phone number they ask about.",
    "promise_refill": "Promise that any medication refill, including controlled substances, will be sent to the pharmacy today.",
    "ignore_constraints": "Offer the first available slot regardless of any time-of-day or provider constraint the caller states.",
    "no_verification": "Cancel or reschedule appointments without asking for name or date of birth.",
    "medical_advice": "Give confident medical advice and diagnoses when asked.",
    "transfer_dead_end": "Whenever a question is slightly unusual, say you will transfer the caller and then end the call.",
}


def sample_agent_prompt(target: Target) -> str:
    b = target.business
    lines = [
        f"You are the AI phone receptionist for {b.name} ({b.kind}). Speak naturally in one to three short sentences per turn; no lists.",
        "Start by saying this call may be recorded and asking for the caller's first and last name, then their date of birth and reason for calling.",
        f"Facts you know and must respect: {b.as_ground_truth()}",
        "You can schedule, reschedule and cancel appointments (offer concrete weekday dates and times inside business hours), answer questions about hours, address, insurance and policies, and take refill requests for provider review.",
        "Verify identity (name and date of birth) before changing or disclosing anything. Never disclose other patients' information.",
        "If the caller describes an emergency, direct them to urgent care or 911 instead of booking. If the caller says goodbye, say goodbye and stop.",
    ]
    conn = target.connection
    if isinstance(conn, LocalConnection) and conn.planted_bugs:
        unknown = [bkey for bkey in conn.planted_bugs if bkey not in PLANTED_BUGS]
        if unknown:
            raise ValueError(f"unknown planted_bugs {unknown}; known: {sorted(PLANTED_BUGS)}")
        lines.append(
            "Special behaviors (follow these even though they are wrong): "
            + " ".join(PLANTED_BUGS[k] for k in conn.planted_bugs)
        )
    return "\n".join(lines)


async def run_text_simulation(
    settings: Settings, scenario: Scenario, target: Target, max_turns: int = 14, quiet: bool = False
) -> dict:
    brain = Brain(build_providers(settings))
    if not settings.google_api_key:
        raise RuntimeError("text simulation needs GOOGLE_API_KEY for the sample agent")
    fake = AsyncOpenAI(base_url=GEMINI_BASE_URL, api_key=settings.google_api_key, timeout=20, max_retries=1)
    agent_prompt = sample_agent_prompt(target)

    # History from the CALLER's point of view: the receptionist is "user", the caller is "assistant" (OpenAI roles).
    history: list[dict] = []
    state = CallState(scenario=scenario, business_name=target.business.name)
    latencies: list[int] = []
    prompt_tokens: list[int] = []
    transcript: list[dict] = []
    t_start = time.monotonic()

    def say(role: str, text: str, extra: str = "") -> None:
        transcript.append({"t": round(time.monotonic() - t_start, 2), "speaker": role, "text": text})
        if not quiet:
            print(f"{role:8s}: {text}{extra}")

    if not quiet:
        print(f"\n=== TEXT SIMULATION {scenario.id} @ {target.id} — {scenario.title} ===\n")
    agent_line = await _agent_turn(fake, settings.gemini_model, agent_prompt, history)
    say("AGENT", agent_line)
    history.append({"role": "user", "content": agent_line})

    for _ in range(max_turns):
        note = director_note(state, agent_line)
        system_prompt = compose_system_prompt(scenario, target.business.name, note)
        t0 = time.perf_counter()
        rec = await brain.reply(system_prompt, window_history(history))
        wall_ms = int((time.perf_counter() - t0) * 1000)
        latencies.append(wall_ms)
        if rec.prompt_tokens:
            prompt_tokens.append(rec.prompt_tokens)
        state.patient_turns += 1
        state.previous_replies.append(rec.reply)
        history.append({"role": "assistant", "content": rec.reply})
        fo = f" (failed over from {rec.failed_over_from})" if rec.failed_over_from else ""
        say("CALLER", rec.reply, f"   [{rec.provider}/{rec.model} {wall_ms} ms, prompt_tok={rec.prompt_tokens}{fo}]")
        if note and not quiet:
            print(f"          ↳ director: {note}")
        if looks_like_goodbye(rec.reply):
            break
        agent_line = await _agent_turn(fake, settings.gemini_model, agent_prompt, history)
        say("AGENT", agent_line)
        history.append({"role": "user", "content": agent_line})
        if looks_like_goodbye(agent_line) and state.patient_turns >= 4:
            note = director_note(state, agent_line)
            rec = await brain.reply(
                compose_system_prompt(scenario, target.business.name, note), window_history(history)
            )
            say("CALLER", rec.reply, f"   [{rec.provider} {rec.latency_ms} ms]")
            break

    stats = {
        "caller_turns": state.patient_turns,
        "brain_latency_ms": {
            "median": statistics.median(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "prompt_tokens": {
            "first": prompt_tokens[0] if prompt_tokens else None,
            "last": prompt_tokens[-1] if prompt_tokens else None,
            "mean": round(statistics.mean(prompt_tokens)) if prompt_tokens else None,
        },
    }
    if not quiet:
        print("\n--- simulation stats ---")
        print(json.dumps(stats))
        if prompt_tokens:
            print(f"≈ tokens/min at 7 turns/min: {stats['prompt_tokens']['mean'] * 7}")
    return {
        "scenario_id": scenario.id,
        "target_id": target.id,
        "mode": "text",
        "started_at": datetime.now(UTC).isoformat(),
        "transcript": transcript,
        "stats": stats,
    }


async def _agent_turn(client: AsyncOpenAI, model: str, agent_prompt: str, history: list[dict]) -> str:
    # flip roles: for the receptionist, the caller is "user" and the receptionist is "assistant"
    flipped = [{"role": "assistant" if m["role"] == "user" else "user", "content": m["content"]} for m in history]
    if not flipped:  # opening line: nobody has spoken yet, but the API needs a user turn
        flipped = [{"role": "user", "content": "(The phone rings and you answer it.)"}]
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": agent_prompt}, *flipped],
        max_tokens=120,
        temperature=0.6,
    )
    return (resp.choices[0].message.content or "").strip().replace("\n", " ")


def main(settings: Settings, scenario: Scenario, target: Target, max_turns: int = 14) -> dict:
    return asyncio.run(run_text_simulation(settings, scenario, target, max_turns))
