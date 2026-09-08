"""Callee personas (a person who answers the phone) and the brain server's ROLE:callee branch — no network."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from voxprobe import server as server_mod
from voxprobe.brain import TurnRecord
from voxprobe.callee import callee_prompt, find_callee, load_callee
from voxprobe.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_bundled_callees_load_and_carry_exact_decisions():
    for path in sorted((ROOT / "callees").glob("*.yaml")):
        p = load_callee(path)
        assert p.id == path.stem
        assert any("say exactly" in d for d in p.decision), p.id
        assert p.manifest_regex


def test_callee_prompt_puts_scripted_lines_and_boundaries_in():
    p = find_callee(ROOT / "callees", "kay2-amelia-reschedules")
    prompt = callee_prompt(p)
    assert "You are Amelia" in prompt
    assert "Friday the fourth at ten works for me." in prompt
    assert "Never:" in prompt and "first name" in prompt


def test_find_callee_unknown():
    with pytest.raises(FileNotFoundError):
        find_callee(ROOT / "callees", "nobody-here")


def test_server_callee_branch(monkeypatch):
    seen = {}

    async def fake_reply(self, system_prompt, history):
        seen["prompt"] = system_prompt
        return TurnRecord(
            reply="Yes, this is Amelia.",
            provider="fake",
            model="fake",
            latency_ms=1,
            prompt_tokens=0,
            completion_tokens=0,
        )

    monkeypatch.setattr(server_mod.Brain, "reply", fake_reply)
    app = server_mod.create_app(Settings(repo_root=ROOT, brain_server_secret="", groq_api_key="dummy"))
    body = {
        "stream": False,
        "call": {"id": "call-callee-1"},
        "messages": [
            {"role": "system", "content": "ROLE:callee CALLEE:kay2-amelia-confirms"},
            {"role": "assistant", "content": "Hello?"},
            {"role": "user", "content": "Hi, this is an AI assistant calling for KAY2 Studios. Is this Amelia?"},
        ],
    }
    with TestClient(app) as c:
        r = c.post("/chat/completions", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == "Yes, this is Amelia."
    assert "brand strategy session" in seen["prompt"] and "Yes, I can make it on the third at ten." in seen["prompt"]


def test_server_callee_branch_needs_marker():
    app = server_mod.create_app(Settings(repo_root=ROOT, brain_server_secret="", groq_api_key="dummy"))
    with TestClient(app) as c:
        r = c.post(
            "/chat/completions", json={"stream": False, "messages": [{"role": "system", "content": "ROLE:callee"}]}
        )
    assert r.status_code == 400
