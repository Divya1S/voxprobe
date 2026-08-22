"""Inbound line: saved-assistant shape and the receptionist-role branch of the brain server (no network)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from voxprobe import server as server_mod
from voxprobe.brain import TurnRecord
from voxprobe.config import Settings
from voxprobe.targets import find_target
from voxprobe.vapi_client import LINE_ASSISTANT_NAME, build_line_assistant

ROOT = Path(__file__).resolve().parents[1]


def _settings(**kw) -> Settings:
    return Settings(public_base_url="https://example.trycloudflare.com", brain_server_secret="s3", repo_root=ROOT, **kw)


def test_line_assistant_answers_as_receptionist_and_records_stereo():
    target = find_target(ROOT / "targets", "local-clinic-buggy")
    a = build_line_assistant(target, _settings(), scenario_id="02-schedule-with-constraints")
    assert a["name"] == LINE_ASSISTANT_NAME
    assert a["firstMessageMode"] == "assistant-speaks-first"
    assert "Sunrise Orthopedics" in a["firstMessage"] and "recorded" in a["firstMessage"]
    assert a["model"]["provider"] == "custom-llm" and a["model"]["url"] == "https://example.trycloudflare.com"
    marker = a["model"]["messages"][0]["content"]
    assert "ROLE:agent" in marker and "TARGET:local-clinic-buggy" in marker and "SCENARIO:02-" in marker
    assert a["artifactPlan"] == {"recordingEnabled": True, "recordingFormat": "mp3"}
    assert a["transcriber"]["provider"] == "deepgram" and a["voice"]["provider"] == "deepgram"
    assert a["server"]["url"].endswith("/vapi/webhook")
    assert a["maxDurationSeconds"] == 240


def test_server_receptionist_branch_uses_sample_agent_prompt(monkeypatch):
    seen = {}

    async def fake_reply(self, system_prompt, history):
        seen["prompt"] = system_prompt
        seen["history"] = history
        return TurnRecord(
            reply="Sure, and your date of birth?",
            provider="fake",
            model="fake",
            latency_ms=1,
            prompt_tokens=0,
            completion_tokens=0,
        )

    monkeypatch.setattr(server_mod.Brain, "reply", fake_reply)
    settings = Settings(repo_root=ROOT, brain_server_secret="", groq_api_key="dummy-for-tests")
    app = server_mod.create_app(settings)
    body = {
        "stream": False,
        "call": {"id": "call-line-1"},
        "messages": [
            {"role": "system", "content": "ROLE:agent TARGET:local-clinic-buggy SCENARIO:02-schedule-with-constraints"},
            {"role": "assistant", "content": "Thank you for calling Sunrise Orthopedics..."},
            {"role": "user", "content": "Hi, this is Daniel Reyes, I'm a new patient."},
        ],
    }
    with TestClient(app) as c:
        r = c.post("/chat/completions", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == "Sure, and your date of birth?"
    assert "AI phone receptionist for Sunrise Orthopedics" in seen["prompt"]
    assert "Special behaviors" in seen["prompt"]  # planted bugs of local-clinic-buggy are in force
    assert seen["history"][-1] == {"role": "user", "content": "Hi, this is Daniel Reyes, I'm a new patient."}


def test_role_marker_defaults_to_patient():
    assert server_mod._role_from([{"role": "system", "content": "SCENARIO:01-x TARGET:y"}]) == "patient"
    assert server_mod._role_from([{"role": "system", "content": "ROLE:agent TARGET:y"}]) == "agent"
