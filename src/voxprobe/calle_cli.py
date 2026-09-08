"""CALL-E via the MCP/CLI path (`calle` CLI): plan_call → run_call → get_call_run.

Why this exists: the Developer REST API and the MCP endpoint authenticate differently (API key vs brokered OAuth), and on
2026-09-07 this account's REST access returned 403 forbidden while the OAuth path worked. The hackathon accepts MCP/CLI
integrations explicitly, so this adapter keeps Gate 0 movable. Same guardrails as the SDK path: allow-listed numbers only,
raw evidence saved under reports/calle/.

The CLI's plan/run tools take a free-text goal (no result_schema); structured grading against a schema stays with the SDK
path — runs made here are graded from transcripts and the run summary only, and reports must say so.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings, assert_allowed_target, normalize_e164
from .scenarios import Scenario

CLI_ENV = {"CALLE_SOURCE": "skills_sh", "CALLE_INTEGRATION": "skills_sh_skill", "CALLE_INTEGRATION_VERSION": "0.1.0"}
TERMINAL = {"COMPLETED", "FAILED", "NO_ANSWER", "DECLINED", "CANCELED", "VOICEMAIL", "BUSY", "EXPIRED"}


class CalleCliError(RuntimeError):
    pass


def _cli(args: list[str], *, timeout_s: float = 180.0) -> dict:
    """Run one `calle` command with --json and return the parsed object (last JSON value on stdout)."""
    proc = subprocess.run(
        ["calle", *args, "--json"],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env={**os.environ, **CLI_ENV},
    )
    out = proc.stdout.strip() or proc.stderr.strip()
    start = out.find("{")
    if start < 0:
        raise CalleCliError(f"calle {args[0]} produced no JSON: {out[:300]}")
    try:
        return json.loads(out[start:])
    except json.JSONDecodeError:  # multiple objects: take the first balanced one
        depth = 0
        for i, ch in enumerate(out[start:], start):
            depth += ch == "{"
            depth -= ch == "}"
            if depth == 0:
                return json.loads(out[start : i + 1])
        raise CalleCliError(f"calle {args[0]}: unparseable JSON output: {out[:300]}") from None


def _tool_payload(res: dict) -> dict:
    """Unwrap `calle mcp call` output: structuredContent when present, else parsed content[0].text."""
    if res.get("ok") is False:
        raise CalleCliError(f"{res.get('error')}")
    r = res.get("result") or res
    if r.get("isError"):
        raise CalleCliError((r.get("content") or [{}])[0].get("text", "tool error")[:400])
    sc = r.get("structuredContent")
    if isinstance(sc, dict) and sc:
        return sc
    text = (r.get("content") or [{}])[0].get("text", "")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


@dataclass
class CliRun:
    stem: str
    run_id: str
    plan: dict
    status: dict
    raw_path: Path


def plan(settings: Settings, goal: str, number: str, *, timeout_s: float = 180.0) -> dict:
    number = normalize_e164(number)
    assert_allowed_target(number, settings.allowed_numbers)
    args = {"user_input": goal, "to_phones": [number], "region": "US", "language": "en"}
    return _tool_payload(
        _cli(
            ["mcp", "call", "plan_call", "--timeout-seconds", "150", "--args-json", json.dumps(args)],
            timeout_s=timeout_s,
        )
    )


def run(
    settings: Settings,
    scenario: Scenario,
    goal: str,
    number: str,
    *,
    poll_s: float = 10.0,
    timeout_s: float = 600.0,
) -> CliRun:
    """Plan and place ONE real call via MCP, then poll get_call_run to a terminal state. Saves raw evidence."""
    p = plan(settings, goal, number)
    if not p.get("ready_to_run") or not p.get("plan_id") or not p.get("confirm_token"):
        raise CalleCliError(f"plan not ready_to_run: questions={p.get('questions')} keys={sorted(p)}")
    started = _tool_payload(
        _cli(
            [
                "mcp",
                "call",
                "run_call",
                "--args-json",
                json.dumps({"plan_id": p["plan_id"], "confirm_token": p["confirm_token"]}),
            ]
        )
    )
    run_id = started.get("run_id") or started.get("id") or p["plan_id"]
    stem = f"calle-cli-{scenario.id}-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
    status: dict = started
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = _tool_payload(_cli(["mcp", "call", "get_call_run", "--args-json", json.dumps({"run_id": run_id})]))
        state = str(status.get("status") or status.get("state") or "").upper()
        if state in TERMINAL:
            break
        time.sleep(poll_s)
    out_dir = settings.reports_dir / "calle"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"{stem}.calle-cli.json"
    raw_path.write_text(
        json.dumps(
            {"stem": stem, "scenario": scenario.id, "goal": goal, "plan": p, "started": started, "final": status},
            indent=2,
            ensure_ascii=False,
        )
    )
    return CliRun(stem, str(run_id), p, status, raw_path)
