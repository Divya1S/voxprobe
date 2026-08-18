# Changelog

All notable changes to voxprobe. Dates are UTC.

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
