# Changelog

All notable changes to voxprobe. Dates are UTC.

## v0.2.1 — 2026-09-08

### Added
- **Callee personas** (`callees/*.yaml`, `voxprobe.callee`): a *person* who answers the phone — the other end for tasks that
  call people (confirmations, reminders). Decisions are verbatim lines so ground truth is exact; the manifest regex proves the
  line was spoken. Brain server `ROLE:callee CALLEE:<id>`; `line.arm_callee`; the keepalive preserves callee arms.
- **Foreign probes** (`probes/foreign-*.yaml`, `otherend.grade_foreign`): another author's task text and `result_schema`
  taken verbatim, graded per callee persona with one regex per field of *their* schema plus the invented-number checks.
  `voxprobe otherend run|grade --callee <id> --probe <foreign-probe>`. Bundled: `foreign-appointment-confirm` (the
  appointment-confirm entry of awesome-phone-call-agents) × Amelia confirms / reschedules / ambiguous — all three PASS on
  real calls.
- `scripts/calle_idempotency_replay.py` (same-key double create probe).

### Fixed
- Disclosure check normalizes typographic apostrophes ("I’m an AI…" graded unknown on a live row).
- `line fetch` waits for Vapi's lingering leg (`silence-timed-out` ~60 s after the caller hangs up) instead of skipping the call.
- Callee stems no longer contain ':'; the `ai-disclosure-probe` greeting keeps the recording notice.
- Numeral-tolerant manifests (TTS/ASR render "the 3rd at 10").

### Results (real calls, 2026-09-08)
- n=2 on the two headline rows: impossible-Saturday booking reported at 0.92 and 0.95 "high"; honest AI disclosure twice.

## v0.2.0 — 2026-09-08 (first PyPI release)

**What's new**: voxprobe can now be the *other end of the line*. An outside AI caller — CALL-E's agent — dials a real phone
number that voxprobe's receptionist answers, and voxprobe grades what the caller *reported* against ground truth it controls.

### Added
- **CALL-E adapter** (`voxprobe calle probe|dry-run|run`, extra `calle`): task text + `result_schema` composed from a scenario so
  the caller's self-report mirrors the scenario's success criteria 1:1; read-only probe; no-call dry run by default; `--yes` +
  allow-list gate; raw CallTask + developer events kept as evidence; same-idempotency-key retries. Also `calle_cli.py` for the
  MCP/CLI path (`plan_call → run_call → get_call_run`).
- **Inbound line** (`voxprobe line up|arm|fetch|down`): a saved Vapi assistant on a free number, custom-LLM → the brain server in
  receptionist role (`ROLE:agent`), Deepgram BYO, stereo MP3; tunnel providers cycled until healthy, keepalive re-arms from the
  latest arm; `fetch` swaps Vapi's channels into voxprobe's convention so `analyze` is unchanged.
- **otherend** (`voxprobe otherend run|grade`): six callee adversity profiles (cooperative, saturday-false-offer,
  evasive-minimal, asks-for-id-details, hold-then-continue, ai-disclosure-probe) with manifest regexes over *our* lines, a
  reference probe with per-profile deterministic expectations, and a grader (self-report accuracy, fabrication checks that ignore
  echoes of our own lines, honest-AI-disclosure check, confidence-vs-correctness calibration) + `REPORT.md`.
- Packaging: data (`scenarios/`, `targets/`, `profiles/`, `probes/`) ships inside the wheel; `VOXPROBE_DATA_DIR` / `VOXPROBE_HOME`
  choose data and output roots when not running from a checkout.

### Results (real calls, 2026-09-08)
- 6/6 profiles graded PASS with the adversity proven manifested in every graded row; measured from the audio across 7 calls:
  CALL-E caller response gap p50 median 2.63 s (2.49–3.01 s), one talk-over event, 12.9 min of audio. Findings and caveats in
  `FEEDBACK.md` and `docs/DEVLOG.md` (2026-09-07).

### Known limitations
- The "hold" profile is nominal (a saved-assistant greeting cannot pause). The judge in `analyze` scores *our* receptionist and
  marks a never-adjudicated criterion "not met" where "n/a" would be honest. Free tunnels churn; the line heals but a call that
  lands mid-churn fails (rows are re-run, never graded).

## v0.1.0 — 2026-08-18 (first tagged release)

**What it does**: persona-driven QA for voice agents — an adaptive simulated caller talks to the agent under test over real
audio (Pipecat 1.7, in-process loopback line or a websocket), both sides are recorded (L = agent, R = caller), the transcript is
rebuilt from the audio, turn-taking/latency is measured for both parties, and findings cite timestamps and quotes.

### Added
- **Scenarios** (14, YAML + Pydantic): persona facts / must-not-invent boundaries, objective, ordered plan, success criteria, bug hypotheses.
- **Targets** with business ground truth: bundled sample receptionist (`local-clinic`), the same agent with **planted bugs**
  (`local-clinic-buggy`), a websocket target (`ws-local-clinic`), an experimental Vapi phone target template.
- **Caller brain**: persona composer + per-turn director + LLM with provider failover (Groq → Groq → Gemini).
- **Audio arena**: two full Pipecat pipelines in one process over a custom loopback transport pair (paced output, virtual mic
  with silence, interruption flush); stereo recording; both-party response latency; deliberate **barge-in driver** with
  yield latency and Pipecat's `interrupted` flag on the agent's turn; **websocket target adapter** + `voxprobe serve-agent`
  (live-validated; known issue: unpaced audio to remote agents).
- **Evidence pipeline**: audio-derived transcript (ffmpeg `silencedetect` regions → Whisper per region), metrics with a named
  `SegmentationPolicy` (response gaps p50/p95, dead air, overlaps, intra-turn pauses), deterministic *measured issues*,
  LLM judge with structured per-criterion / per-hypothesis verdicts, `decide()` PASS/FAIL without an LLM.
- **Planted-bug detection benchmark** (`voxprobe bench`): one bug at a time vs a clean control, k repeats, strict
  nearest-text judge detector + transparent symptom rules, precision/recall/F1, pass@1/pass@k/pass^k, *manifested* column, resumable,
  models recorded per run. Result on 2026-08-17/18: **114 runs, P 1.0 / R 0.93 (53/57) / F1 0.964, 0 false alarms**.
- **Judge calibration** (`voxprobe calibrate`): stratified labelling sheet, agreement + Cohen's κ. human-01: 25 claims, 25/25 agree.
- **Golden calibration test** on a committed synthetic stereo fixture (scripted gaps reproduced within 0.25 s, ffmpeg-only, in CI).
- Docs: README with an annotated stereo-waveform hero, ARCHITECTURE.md (Mermaid), ADR-001/002, ROADMAP, DEVLOG.

### Known limitations (stated on purpose)
- The sample agent has no booking store: "hallucinated record" hypotheses cannot be adjudicated against it and are not benchmarked.
- Free-tier models drift (two retirements in two days); defaults are pinned to what worked on the release date, with failover.
- Barge-in "yield" is measured from the trigger and includes the caller's own TTS time-to-first-byte; the `interrupted` flag is available only over the loopback line.
- Text-mode runs are turn-paced for free-tier quotas and carry no timing; audio-mode runs do.
- The phone adapter (Vapi) is experimental and requires paid telephony; every outbound number must be on `ALLOWED_NUMBERS_E164`.
