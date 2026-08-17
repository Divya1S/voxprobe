"""Exercise the brain server exactly the way Vapi will (needs GROQ/GOOGLE keys in .env — one real LLM call)."""

import json
import os

import pytest
from fastapi.testclient import TestClient

from voxprobe.config import load_settings
from voxprobe.server import create_app

pytestmark = pytest.mark.skipif(not (os.environ.get("GROQ_API_KEY") or os.path.exists(".env")), reason="needs LLM keys")


@pytest.fixture(scope="module")
def client():
    settings = load_settings()
    return TestClient(create_app(settings)), settings


def _vapi_style_request(scenario_id: str) -> dict:
    return {
        "model": "custom",
        "stream": True,
        "call": {"id": "test-call-0001"},
        "messages": [
            {"role": "system", "content": f"SCENARIO:{scenario_id} TARGET:local-clinic"},
            {
                "role": "user",
                "content": "Thanks for calling. This call may be recorded. May I have your first and last name?",
            },
        ],
    }


def test_health(client):
    c, _ = client
    r = c.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_rejects_bad_token_when_secret_set(client):
    c, settings = client
    if not settings.brain_server_secret:
        pytest.skip("no BRAIN_SERVER_SECRET set")
    r = c.post(
        "/chat/completions",
        json=_vapi_style_request("01-schedule-new-patient"),
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401


def test_streams_openai_chunks_with_a_short_spoken_reply(client):
    c, settings = client
    headers = {"Authorization": f"Bearer {settings.brain_server_secret}"} if settings.brain_server_secret else {}
    with c.stream(
        "POST", "/chat/completions", json=_vapi_style_request("01-schedule-new-patient"), headers=headers
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        lines = [ln for ln in r.iter_lines() if ln.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    first = json.loads(lines[0][len("data: ") :])
    text = first["choices"][0]["delta"]["content"]
    assert 0 < len(text) < 300, text
    assert "Maya" in text or "Thompson" in text  # she was asked her name
    assert "*" not in text and "\n" not in text  # speakable


def test_missing_marker_is_a_400(client):
    c, settings = client
    headers = {"Authorization": f"Bearer {settings.brain_server_secret}"} if settings.brain_server_secret else {}
    body = _vapi_style_request("01-schedule-new-patient")
    body["messages"][0]["content"] = "You are a helpful assistant."
    r = c.post("/chat/completions", json=body, headers=headers)
    assert r.status_code == 400
