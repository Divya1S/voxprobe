"""Command-line entry point.

voxprobe list                                        scenarios and targets
voxprobe simulate --scenario 01 --target local-clinic   local run against the bundled sample agent (text mode; audio arena coming)
voxprobe call --scenario 01 --target my-phone-agent  real phone call through the optional Vapi adapter (tunnel + brain server + call + evidence)
voxprobe serve                                       run the brain server only (external tunnel)
voxprobe analyze <stem>...                           re-transcribe + metrics + judge draft for recorded call(s)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import subprocess
import time

import httpx
import uvicorn

from .config import load_settings
from .scenarios import find_scenario, load_all_scenarios
from .targets import find_target, load_all_targets

TUNNEL_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


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
    if target.kind != "local":
        raise SystemExit(f"target {target.id} is a {target.kind} target — `simulate` needs a local target")
    if args.mode != "text":
        raise SystemExit("audio mode is not built yet — see docs/ROADMAP.md")
    simulate.main(settings, scenario, target, max_turns=args.max_turns)


def cmd_serve(args) -> None:
    from .server import create_app

    settings = load_settings()
    uvicorn.run(create_app(settings), host=settings.brain_host, port=settings.brain_port, log_level="info")


async def _start_tunnel(port: int, timeout_s: int = 90) -> tuple[subprocess.Popen, str]:
    """Spawn a cloudflared quick tunnel; return (process, public https URL) once the tunnel is REGISTERED.

    cloudflared prints the URL before the connection is established, so we also wait for its
    "Registered tunnel connection" line — otherwise the first health checks 1033/530 for a while.
    """
    log = logging.getLogger("voxprobe.tunnel")
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    t0 = time.monotonic()
    url, registered = None, False
    loop = asyncio.get_running_loop()
    while time.monotonic() - t0 < timeout_s and not (url and registered):
        line = await loop.run_in_executor(None, proc.stdout.readline)
        if not line:
            break
        if " ERR " in line:
            log.warning("cloudflared: %s", line.strip()[:200])
        hit = TUNNEL_URL_RE.search(line)
        if hit:
            url = hit.group(0)
        if "Registered tunnel connection" in line:
            registered = True
    if not url:
        proc.terminate()
        raise RuntimeError("cloudflared did not print a trycloudflare.com URL (is cloudflared installed?)")
    if not registered:
        log.warning("tunnel URL found but no 'Registered tunnel connection' within %ss — continuing anyway", timeout_s)
    loop.run_in_executor(None, _drain, proc, log)
    return proc, url


def _drain(proc: subprocess.Popen, log: logging.Logger) -> None:
    for line in proc.stdout:
        if " ERR " in line:
            log.warning("cloudflared: %s", line.strip()[:200])


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
    p.add_argument("--max-turns", type=int, default=14)
    p.set_defaults(fn=cmd_simulate)

    sub.add_parser("serve", help="run the brain server").set_defaults(fn=cmd_serve)

    p = sub.add_parser("call", help="real phone call through the Vapi adapter (tunnel + server + call + evidence)")
    p.add_argument("--scenario", required=True)
    p.add_argument("--target", required=True)
    p.set_defaults(fn=cmd_call)

    p = sub.add_parser("analyze", help="re-transcribe + metrics + judge draft for recorded call(s) by artifact stem")
    p.add_argument("stems", nargs="+")
    p.set_defaults(fn=cmd_analyze)

    args = ap.parse_args(argv)
    _logging(args.verbose)
    args.fn(args)


if __name__ == "__main__":
    main()
