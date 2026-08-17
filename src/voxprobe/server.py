"""The brain server Vapi talks to during a call.

Routes
------
POST /chat/completions   Vapi's custom-LLM hook. OpenAI chat-completions request in (full history), OpenAI SSE
                         chunks out. We ignore Vapi's system message except for the ``SCENARIO:<id>`` marker,
                         rebuild the real persona prompt from the scenario file, add the director's note, ask
                         the brain, and stream the shaped reply back.
POST /vapi/webhook       Vapi server messages (transcript, speech-update, user-interrupted, status-update,
                         end-of-call-report, ...). Appended verbatim + receive timestamp to
                         reports/events/<call_id>.jsonl — the raw material for latency/turn-taking evidence.
GET  /health             Liveness check used by the dialer before it places a call.

Both POST routes require ``Authorization: Bearer <BRAIN_SERVER_SECRET>``.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .brain import Brain, TurnRecord, build_providers, window_history
from .config import Settings, load_settings
from .director import CallState, director_note
from .persona import compose_system_prompt
from .scenarios import Scenario, find_scenario
from .targets import Target, find_target

log = logging.getLogger("voxprobe.server")

SCENARIO_MARKER = re.compile(r"SCENARIO:([0-9]{2}-[a-z0-9-]+)")
TARGET_MARKER = re.compile(r"TARGET:([a-z0-9-]+)")


class CallRegistry:
    """Per-call state (director memory + turn records), keyed by Vapi call id."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._states: dict[str, CallState] = {}
        self._turns: dict[str, list[TurnRecord]] = {}
        self._scenario_cache: dict[str, Scenario] = {}
        self._target_cache: dict[str, Target] = {}

    def scenario(self, scenario_id: str) -> Scenario:
        if scenario_id not in self._scenario_cache:
            self._scenario_cache[scenario_id] = find_scenario(self.settings.scenarios_dir, scenario_id)
        return self._scenario_cache[scenario_id]

    def target(self, target_id: str) -> Target:
        if target_id not in self._target_cache:
            self._target_cache[target_id] = find_target(self.settings.targets_dir, target_id)
        return self._target_cache[target_id]

    def state(self, call_id: str, scenario_id: str, target_id: str) -> CallState:
        if call_id not in self._states:
            self._states[call_id] = CallState(scenario=self.scenario(scenario_id), business_name=self.target(target_id).business.name)
            self._turns[call_id] = []
        return self._states[call_id]

    def record_turn(self, call_id: str, rec: TurnRecord) -> None:
        self._turns.setdefault(call_id, []).append(rec)

    def turns(self, call_id: str) -> list[TurnRecord]:
        return self._turns.get(call_id, [])


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="voxprobe brain", version="0.1.0")
    registry = CallRegistry(settings)
    brain = Brain(build_providers(settings))
    events_dir = settings.reports_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)

    def _auth(authorization: str | None) -> None:
        expected = settings.brain_server_secret
        if not expected:
            return  # no secret configured (local dry-runs); production runs always set one
        if authorization != f"Bearer {expected}":
            raise HTTPException(status_code=401, detail="bad or missing bearer token")

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "providers": [p.name for p in brain.providers]}

    @app.post("/chat/completions")
    async def chat_completions(request: Request, authorization: str | None = Header(default=None)):
        _auth(authorization)
        body = await request.json()
        messages: list[dict] = body.get("messages", [])
        call = body.get("call") or {}
        call_id = call.get("id") or body.get("callId") or "no-call-id"
        if not registry.turns(call_id):  # first request of a call: learn the protocol shape once
            log.info("[%s] first custom-llm request keys=%s call_keys=%s n_messages=%d",
                     call_id[:8], sorted(k for k in body if k != "messages"), sorted(call.keys()), len(messages))

        scenario_id, target_id = _markers_from(messages, body)
        if not scenario_id or not target_id:
            raise HTTPException(status_code=400, detail="system message must carry SCENARIO:<id> and TARGET:<id> markers")

        state = registry.state(call_id, scenario_id, target_id)
        history = window_history(messages)
        agent_last = next((m["content"] for m in reversed(history) if m["role"] == "user"), None)
        note = director_note(state, agent_last)
        system_prompt = compose_system_prompt(state.scenario, state.business_name, note)

        t0 = time.perf_counter()
        rec = await brain.reply(system_prompt, history)
        state.patient_turns += 1
        state.previous_replies.append(rec.reply)
        registry.record_turn(call_id, rec)
        _append_event(events_dir, call_id, {
            "type": "brain-turn", "received_at": time.time(), "scenario": scenario_id,
            "turn": state.patient_turns, "provider": rec.provider, "model": rec.model,
            "latency_ms": rec.latency_ms, "server_ms": int((time.perf_counter() - t0) * 1000),
            "prompt_tokens": rec.prompt_tokens, "completion_tokens": rec.completion_tokens,
            "failed_over_from": rec.failed_over_from, "director": note,
            "agent_last": agent_last, "reply": rec.reply,
        })
        log.info("[%s] turn %d %s %dms tok=%s :: %s", call_id[:8], state.patient_turns, rec.provider,
                 rec.latency_ms, rec.prompt_tokens, rec.reply)

        if body.get("stream", True):
            return StreamingResponse(_sse(rec.reply, rec.model), media_type="text/event-stream")
        return JSONResponse(_completion_json(rec.reply, rec.model))

    @app.post("/vapi/webhook")
    async def vapi_webhook(request: Request, authorization: str | None = Header(default=None)):
        _auth(authorization)
        body = await request.json()
        msg = body.get("message", body)
        call = msg.get("call") or body.get("call") or {}
        call_id = call.get("id") or "no-call-id"
        event = {"type": msg.get("type"), "received_at": time.time(), "message": msg}
        _append_event(events_dir, call_id, event)
        mtype = msg.get("type")
        if mtype == "transcript" and msg.get("transcriptType") == "final":
            log.info("[%s] %-9s %s", call_id[:8], msg.get("role"), msg.get("transcript"))
        elif mtype in ("status-update", "end-of-call-report", "user-interrupted", "hang"):
            log.info("[%s] event %s %s", call_id[:8], mtype, msg.get("status") or msg.get("endedReason") or "")
        return {"ok": True}

    return app


def _markers_from(messages: list[dict], body: dict) -> tuple[str | None, str | None]:
    scenario_id = target_id = None
    for m in messages:
        if m.get("role") == "system" and isinstance(m.get("content"), str):
            s, t = SCENARIO_MARKER.search(m["content"]), TARGET_MARKER.search(m["content"])
            scenario_id = scenario_id or (s.group(1) if s else None)
            target_id = target_id or (t.group(1) if t else None)
    if not (scenario_id and target_id):  # fallback: metadata attached when creating the call
        meta = (body.get("call") or {}).get("assistantOverrides", {}).get("metadata") or (body.get("metadata") or {})
        if isinstance(meta, dict):
            scenario_id = scenario_id or meta.get("scenario_id")
            target_id = target_id or meta.get("target_id")
    return scenario_id, target_id


def _append_event(events_dir: Path, call_id: str, event: dict) -> None:
    with (events_dir / f"{call_id}.jsonl").open("a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _completion_json(text: str, model: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
    }


async def _sse(text: str, model: str):
    """OpenAI-style streaming: one content chunk, one stop chunk, [DONE]."""
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    def chunk(delta: dict, finish: str | None) -> str:
        payload = {
            "id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(payload)}\n\n"

    yield chunk({"role": "assistant", "content": text}, None)
    yield chunk({}, "stop")
    yield "data: [DONE]\n\n"


app = None  # created lazily by `voxprobe serve` (see cli.py) so imports never require a .env
