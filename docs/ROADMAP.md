# voxprobe — roadmap

voxprobe is a persona-driven QA framework for voice agents: an adaptive simulated caller talks to the agent under test over
real audio, both sides are recorded, the transcript is rebuilt from the audio, turn-taking/latency is measured for both parties,
and findings cite timestamps and quotes.

## Done

| # | Milestone |
|---|---|
| M1 | **Core**: scenarios (YAML + Pydantic), persona composer, per-turn director, LLM brain with provider failover (Groq → Groq fallback → Gemini), targets with business ground truth, dial allow-list guard, evidence bundle, audio-timed re-transcription (ffmpeg silencedetect + Whisper per region), turn-taking/latency metrics, LLM-judge draft, text-mode local simulation against a bundled sample agent with **planted bugs** |
| M2 | **Audio arena (Pipecat 1.7)**: in-process loopback transport pair (paced output, virtual mic with silence, interruption flush); simulated caller ↔ sample agent as two full voice pipelines; stereo recording (L = agent, R = caller); both-party response latency; two real example runs |
| P1 | **Truth pass**: metrics no longer conflate dead air with latency; p95 gated on n ≥ 5; deterministic *measured issues*; unbacked claims removed; examples corrected |
| P2 | **Thesis visible**: ARCHITECTURE.md + Mermaid, annotated stereo-waveform hero, prior-art table (naming `pipecat.evals` first), metrics glossary, ADR-001/002 |
| P3 | **The number**: `voxprobe bench` — 8 bug classes × scenarios × {planted, clean} × k=3 = 114 runs; strict nearest-text judge detector + symptom rules; **P 1.0 / R 0.93 / F1 0.964, 0 false alarms**; *manifested* column; resumable; models recorded per run |
| P4 | **Prove the instrument**: golden calibration test on a committed synthetic fixture (CI, key-free), loopback tests, human calibration (25/25 agree), deliberate barge-in driver with yield latency + Pipecat's `interrupted` flag, one live example (arena-09) |
| P5 (part) | **Websocket target adapter** + `voxprobe serve-agent` — live-validated end to end (arena-01 over ws://localhost:8765) |
| P6 (part) | v0.1.0 tag, CHANGELOG |

## Next

| # | Item | Why |
|---|---|---|
| 1 | **Gemini Live** speech-to-speech as a real, non-planted target (free tier); document that frame-based latency observers go blank there while audio-derived timing still works | a run against an agent we did not write; the strongest argument for the audio-first design |
| 2 | **Pace the websocket path** (a receiving-side virtual mic like the loopback's) — the smoke run showed the remote agent's STT missing words from bursty audio | makes websocket results comparable to loopback |
| 3 | Sample agent with a real booking store (tools) so "hallucinated record" hypotheses become adjudicable and benchmarkable | closes the biggest stated limitation |
| 4 | Second human rater for the calibration sheet; larger sample | κ from one rater at 100% is a sanity check, not evidence |
| 5 | Write-up ("we caught a voice agent booking a Saturday at a weekday-only clinic — and measured how often the detector is right") | distribution |

Deferred on purpose: Docker, docs site, PyPI, CI matrix, offline (Kokoro/Whisper/Ollama) profile, acoustic perturbation ladder,
phone-adapter work (frozen as experimental).

## Design principles
- **Evidence over claims**: every finding cites a timestamp and a verbatim quote from an audio-derived transcript.
- **Timing from audio, words from ASR**: turn-taking metrics come from each channel's energy envelope; Whisper only supplies words.
- **Deterministic where possible**: dead air and talk-over are measured; only content is judged — and the judge is calibrated.
- **The simulator must sound like a person**: short turns, answers first, steers second, never reads its goals aloud.
- **Free by default**: free tiers or local models; paid telephony is optional and isolated behind adapters.
- **Never ship a claim `src/` doesn't back.**
