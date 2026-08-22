"""Command-line entry point.

voxprobe list                                          scenarios and targets
voxprobe simulate --scenario 02 --target local-clinic-buggy --mode text|audio   local arena vs the bundled sample agent
voxprobe simulate --scenario 01 --target ws-local-clinic --mode audio           the same caller over a websocket target
voxprobe serve-agent --target local-clinic --port 8765  expose the sample agent over Pipecat's websocket protocol
voxprobe bench --name <name> -k 3                      planted-bug detection benchmark (precision/recall/F1, pass@k)
voxprobe calibrate sample|score ...                    judge calibration sheet + human agreement / kappa
voxprobe analyze <stem>...                             re-transcribe + metrics + judge for recorded runs
voxprobe calle probe|dry-run|run ...                   CALL-E's outbound agent as the caller (plan-then-dial; allow-listed numbers only)
voxprobe line up|arm|fetch|down ...                    the inbound line: our receptionist under test answering the free Vapi number
voxprobe call --scenario 01 --target <vapi-target>     experimental phone adapter (tunnel + brain server + call)
voxprobe serve                                         brain server only (external tunnel)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import subprocess
import time
from pathlib import Path

import httpx
import uvicorn

from .config import load_settings
from .scenarios import find_scenario, load_all_scenarios
from .targets import find_target, load_all_targets

TUNNEL_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
log = logging.getLogger("voxprobe.tunnel")


def _logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def cmd_list(args) -> None:
    settings = load_settings()
    print("Scenarios:")
    for s in load_all_scenarios(settings.scenarios_dir):
        print(f"  {s.id:34s} [{s.category:12s}] {s.title}")
    print("\nTargets:")
    for t in load_all_targets(settings.targets_dir):
        print(f"  {t.id:34s} [{t.kind:12s}] {t.name}")


def cmd_simulate(args) -> None:
    from . import simulate

    settings = load_settings()
    scenario = find_scenario(settings.scenarios_dir, args.scenario)
    target = find_target(settings.targets_dir, args.target)
    if target.kind not in ("local", "websocket"):
        raise SystemExit(f"target {target.id} is a {target.kind} target — `simulate` needs a local or websocket target")
    if args.mode == "text" and target.kind != "local":
        raise SystemExit("text mode drives the bundled sample agent only; use --mode audio for websocket targets")
    if args.mode == "text":
        simulate.main(settings, scenario, target, max_turns=args.max_turns)
        return
    from .analyze import analyze_call
    from .arena.run import main as run_arena

    result = run_arena(settings, scenario, target, max_duration_s=args.max_seconds)
    print(f"\n● arena run {result.stem}: {result.duration_s}s, ended {result.ended_reason}")
    print(f"● recording  → {result.files.get('recording_mp3')}")
    print(f"● transcript → {result.files.get('transcript_md')}")
    if result.caller_latencies_s:
        print(f"● caller response latency (s): {result.caller_latencies_s}")
    if result.agent_latencies_s:
        print(f"● agent  response latency (s): {result.agent_latencies_s}")
    if result.files.get("recording_mp3") and not args.no_analyze:
        out = analyze_call(settings, result.stem)
        print(f"● analysis   → {out.relative_to(settings.repo_root)}")


def cmd_serve(args) -> None:
    from .server import create_app

    settings = load_settings()
    uvicorn.run(create_app(settings), host=settings.brain_host, port=settings.brain_port, log_level="info")


LHR_URL_RE = re.compile(r"https://[a-z0-9-]+\.lhr\.life")


async def _start_cloudflared(port: int, timeout_s: int) -> tuple[subprocess.Popen, str] | None:
    """cloudflared quick tunnel; None if it cannot register within timeout_s (some networks reset the API call)."""
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url, registered, t0 = None, False, time.monotonic()
    loop = asyncio.get_running_loop()
    while time.monotonic() - t0 < timeout_s and proc.poll() is None:
        line = await loop.run_in_executor(None, proc.stdout.readline)
        if not line:
            break
        if "failed to request quick Tunnel" in line or "ERR" in line:
            log.warning("cloudflared: %s", line.strip()[:200])
        m = TUNNEL_URL_RE.search(line)
        if m:
            url = m.group(0)
        if "Registered tunnel connection" in line:
            registered = True
            break
    if url and registered:
        return proc, url
    proc.terminate()
    return None


async def _start_localhost_run(port: int, timeout_s: int) -> tuple[subprocess.Popen, str]:
    """$0, no-account fallback: ssh -R through localhost.run (URL https://<id>.lhr.life)."""
    proc = subprocess.Popen(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ExitOnForwardFailure=yes",
            "-R",
            f"80:127.0.0.1:{port}",
            "nokey@localhost.run",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    loop = asyncio.get_running_loop()
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s and proc.poll() is None:
        line = await loop.run_in_executor(None, proc.stdout.readline)
        if not line:
            break
        m = LHR_URL_RE.search(line)
        if m:
            return proc, m.group(0)
    proc.terminate()
    raise RuntimeError("localhost.run did not print a *.lhr.life URL (is outbound ssh allowed?)")


async def _start_tunnel(port: int, timeout_s: int = 90) -> tuple[subprocess.Popen, str]:
    """Expose the local brain server on a public https URL for $0.

    Order: VOXPROBE_TUNNEL env (cloudflared | localhost.run) if set; else cloudflared quick tunnel, then localhost.run when
    cloudflared cannot register (observed 2026-08-21: api.trycloudflare.com connection reset on some networks).
    """
    import os

    pref = os.environ.get("VOXPROBE_TUNNEL", "").strip().lower()
    if pref in ("", "cloudflared"):
        got = await _start_cloudflared(port, timeout_s if pref else 40)
        if got:
            return got
        if pref == "cloudflared":
            raise RuntimeError("cloudflared could not register a quick tunnel")
        log.warning("cloudflared unavailable — falling back to localhost.run")
    return await _start_localhost_run(port, timeout_s)


async def _wait_healthy(url: str, timeout_s: int = 120) -> None:
    async with httpx.AsyncClient(timeout=10) as c:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout_s:
            try:
                r = await c.get(f"{url}/health")
                if r.status_code == 200 and r.json().get("ok"):
                    return
            except Exception:
                pass
            await asyncio.sleep(2)
    raise RuntimeError(f"{url}/health never became reachable through the tunnel")


async def _call_all_in_one(args) -> None:
    from .call_runner import run_call, with_public_url
    from .server import create_app

    settings = load_settings()
    scenario = find_scenario(settings.scenarios_dir, args.scenario)
    target = find_target(settings.targets_dir, args.target)

    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host=settings.brain_host, port=settings.brain_port, log_level="warning")
    )
    server_task = asyncio.create_task(server.serve())
    proc, url = await _start_tunnel(settings.brain_port)
    print(f"● tunnel up: {url}")
    try:
        await _wait_healthy(url)
        print("● brain server healthy through tunnel")
        settings = with_public_url(settings, url)
        await run_call(settings, scenario, target)
        await asyncio.sleep(5)  # let late webhooks (end-of-call-report) land in the event log
    finally:
        proc.terminate()
        server.should_exit = True
        await server_task


def cmd_call(args) -> None:
    asyncio.run(_call_all_in_one(args))


def cmd_bench(args) -> None:
    from . import bench

    settings = load_settings()
    out = bench.main(
        settings,
        args.name,
        args.bugs,
        args.k,
        resume=not args.no_resume,
        concurrency=args.concurrency,
        max_turns=args.max_turns,
    )
    print(f"● bench summary → {(out / 'summary.md').relative_to(settings.repo_root)}")
    print((out / "summary.md").read_text())


def cmd_serve_agent(args) -> None:
    from .arena.run import serve_main

    settings = load_settings()
    target = find_target(settings.targets_dir, args.target)
    serve_main(settings, target, args.host, args.port)


def cmd_calibrate(args) -> None:
    from . import calibrate

    settings = load_settings()
    if args.action == "sample":
        out = calibrate.sample(settings, args.name, n=args.n, seed=args.seed, pattern=args.pattern)
        print(
            f"● labelling sheet → {out.relative_to(settings.repo_root)}  (fill the 'Human:' lines, then `voxprobe calibrate score {out}`)"
        )
    else:
        import json as _json

        print(_json.dumps(calibrate.score(Path(args.name)), indent=2))


def cmd_calle(args) -> None:
    import json as _json

    from . import calle_client

    settings = load_settings()
    if args.action == "probe":
        print(_json.dumps(calle_client.probe(settings), indent=2))
        return
    scenario = find_scenario(settings.scenarios_dir, args.scenario)
    number = args.to or settings.calle_target_number
    if not number:
        raise SystemExit("need --to +1... (or CALLE_TARGET_E164 in .env)")
    if args.action == "dry-run":
        print(_json.dumps(calle_client.dry_run(scenario, number, args.business), indent=2, ensure_ascii=False))
        return
    if not args.yes:
        raise SystemExit("this places a REAL call and spends one CALL-E call — re-run with --yes")
    res = calle_client.run(
        settings,
        scenario,
        number,
        args.business,
        timeout_s=args.timeout,
        retry_every_s=args.retry_every * 60,
        retry_for_s=args.retry_for * 3600,
    )
    t = res.task
    print(
        f"● CALL-E call {res.call_id}: status={t.get('status')} task_completed={t.get('task_completed')} confidence={t.get('completion_confidence')}"
    )
    print(f"● raw evidence → {res.raw_path.relative_to(settings.repo_root)}")
    print(f"● transcript   → {res.transcript_path.relative_to(settings.repo_root)}")
    print(res.transcript_path.read_text())


def cmd_line(args) -> None:
    from . import line

    settings = load_settings()
    if args.action == "up":
        line.main_up(settings, args.target, args.scenario, args.greeting)
    elif args.action == "arm":
        state = line.LineState.load(settings)
        target = find_target(settings.targets_dir, args.target or state.target_id)
        sid = find_scenario(settings.scenarios_dir, args.scenario).id if args.scenario else state.scenario_id
        st = asyncio.run(
            line.arm(line.with_public_url(settings, state.public_url), target, scenario_id=sid, greeting=args.greeting)
        )
        print(f"● line re-armed: target '{st.target_id}' scenario '{st.scenario_id or '-'}' greeting: {st.greeting}")
    elif args.action == "fetch":
        metas = asyncio.run(line.fetch(settings, limit=args.limit, scenario_id=args.scenario, call_id=args.call_id))
        for m in metas:
            print(
                f"● {m['stem']}: {m.get('ended_reason')} from {m.get('from')} · {m['files'].get('recording_mp3') or 'no recording'}"
            )
        if not metas:
            print("no ended inbound calls found on the line")
    elif args.action == "down":
        asyncio.run(line.down(settings))
        print("● assistant detached from the number")


def cmd_analyze(args) -> None:
    from .analyze import analyze_call

    settings = load_settings()
    for stem in args.stems:
        out = analyze_call(settings, stem)
        print(f"● analysis → {out.relative_to(settings.repo_root)}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="voxprobe", description="Persona-driven QA for voice agents")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list scenarios and targets").set_defaults(fn=cmd_list)

    p = sub.add_parser("simulate", help="local run against the bundled sample agent")
    p.add_argument("--scenario", required=True)
    p.add_argument("--target", default="local-clinic")
    p.add_argument("--mode", choices=["text", "audio"], default="text")
    p.add_argument("--max-turns", type=int, default=14, help="text mode: max caller turns")
    p.add_argument("--max-seconds", type=int, default=None, help="audio mode: hard cap on call length")
    p.add_argument("--no-analyze", action="store_true", help="audio mode: skip re-transcription/metrics/judge")
    p.set_defaults(fn=cmd_simulate)

    sub.add_parser("serve", help="run the brain server").set_defaults(fn=cmd_serve)

    p = sub.add_parser("call", help="real phone call through the Vapi adapter (tunnel + server + call + evidence)")
    p.add_argument("--scenario", required=True)
    p.add_argument("--target", required=True)
    p.set_defaults(fn=cmd_call)

    p = sub.add_parser("bench", help="planted-bug detection benchmark (text mode): precision/recall/F1 per bug class")
    p.add_argument("--name", default=None, help="results dir name under reports/bench/ (default: date)")
    p.add_argument("--bugs", nargs="*", default=None, help="subset of bug classes (default: all)")
    p.add_argument("-k", type=int, default=3, help="repeats per (bug, scenario, target) cell")
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--max-turns", type=int, default=12)
    p.add_argument("--no-resume", action="store_true")
    p.set_defaults(fn=cmd_bench)

    p = sub.add_parser("serve-agent", help="expose the bundled sample agent over Pipecat's websocket protocol")
    p.add_argument("--target", default="local-clinic")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(fn=cmd_serve_agent)

    p = sub.add_parser(
        "calibrate", help="judge calibration: sample claims into a labelling sheet, then score human agreement"
    )
    p.add_argument("action", choices=["sample", "score"])
    p.add_argument("name", help="sheet name (sample) or path to the filled sheet (score)")
    p.add_argument("-n", type=int, default=25)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--pattern", default="*.analysis.json", help="which analyses to sample from (glob under reports/)")
    p.set_defaults(fn=cmd_calibrate)

    p = sub.add_parser(
        "calle", help="CALL-E adapter: probe (read-only auth check), dry-run (print task+schema), run (one real call)"
    )
    p.add_argument("action", choices=["probe", "dry-run", "run"])
    p.add_argument("--scenario", help="scenario number or id (dry-run/run)")
    p.add_argument("--to", help="recipient E.164 (default CALLE_TARGET_E164); must be on ALLOWED_NUMBERS_E164")
    p.add_argument("--business", default="Sunrise Orthopedics", help="how the task names the place being called")
    p.add_argument("--timeout", type=float, default=600.0, help="seconds to wait for the CallTask to finish")
    p.add_argument("--yes", action="store_true", help="confirm spending one real CALL-E call")
    p.add_argument(
        "--retry-every", type=float, default=0.0, help="minutes between retries when CALL-E is unavailable (503)"
    )
    p.add_argument("--retry-for", type=float, default=0.0, help="hours to keep retrying (same idempotency key)")
    p.set_defaults(fn=cmd_calle)

    p = sub.add_parser(
        "line", help="inbound line: up (server+tunnel+assistant on the free number), arm, fetch artifacts, down"
    )
    p.add_argument("action", choices=["up", "arm", "fetch", "down"])
    p.add_argument("--target", default="local-clinic", help="receptionist profile (target id) the line answers as")
    p.add_argument("--scenario", help="the persona the CALLER is expected to play (attached to evidence for the judge)")
    p.add_argument("--greeting", help="override the receptionist's first line")
    p.add_argument("--limit", type=int, default=5, help="fetch: how many recent calls to look at")
    p.add_argument("--call-id", help="fetch: one specific Vapi call id")
    p.set_defaults(fn=cmd_line)

    p = sub.add_parser("analyze", help="re-transcribe + metrics + judge draft for recorded call(s) by artifact stem")
    p.add_argument("stems", nargs="+")
    p.set_defaults(fn=cmd_analyze)

    args = ap.parse_args(argv)
    _logging(args.verbose)
    if getattr(args, "cmd", None) == "bench" and not args.name:
        from datetime import UTC, datetime

        args.name = datetime.now(UTC).strftime("%Y%m%d")
    args.fn(args)


if __name__ == "__main__":
    main()
