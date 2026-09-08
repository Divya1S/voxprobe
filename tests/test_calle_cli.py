"""MCP/CLI adapter: output unwrapping and the dial guard (no calle binary, no network)."""

from __future__ import annotations

import pytest

from voxprobe import calle_cli
from voxprobe.calle_cli import CalleCliError, _tool_payload
from voxprobe.config import Settings, TargetNumberError


def test_tool_payload_prefers_structured_content():
    res = {"ok": True, "result": {"isError": False, "structuredContent": {"ready_to_run": True, "plan_id": "p1"}}}
    assert _tool_payload(res)["plan_id"] == "p1"


def test_tool_payload_parses_text_json_and_raises_on_error():
    res = {"ok": True, "result": {"isError": False, "content": [{"type": "text", "text": '{"run_id": "r1"}'}]}}
    assert _tool_payload(res)["run_id"] == "r1"
    with pytest.raises(CalleCliError, match="429"):
        _tool_payload({"ok": True, "result": {"isError": True, "content": [{"type": "text", "text": "Error … 429 …"}]}})
    with pytest.raises(CalleCliError):
        _tool_payload({"ok": False, "error": {"code": "auth_required"}})


def test_plan_refuses_numbers_off_the_allow_list():
    settings = Settings(allowed_numbers=frozenset({"+14155550100"}))
    with pytest.raises(TargetNumberError, match="Refusing to dial"):
        calle_cli.plan(settings, "say hello", "+14155550199")
