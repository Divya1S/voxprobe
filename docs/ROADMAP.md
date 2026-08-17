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

## Next (in this order — chosen after research on what reviewers check first)

| # | Phase | Deliverables | Evidence it produces |
|---|---|---|---|
| P2 | **Thesis visible** | ARCHITECTURE.md + Mermaid, annotated stereo-waveform hero, prior-art table (naming `pipecat.evals` first), metrics glossary, ADR-001/002 | diagram · waveform image · comparison table |
| P3 | **The number** | `voxprobe bench`: 14 scenarios × {clean, buggy} × k runs (text mode full matrix, audio subset); deterministic per-criterion pass/fail with non-zero exit; per-bug **precision / recall / F1**, **false-alarm rate on the clean control**, pass@1 / pass@k; results JSON + README table + reproduce command | the scorecard and the detection matrix |
| P4 | **Prove the instrument** | golden tests on the synthetic stereo fixture (0.8/0.7/0.9 s → measured values as CI assertions), loopback pacing/flush unit tests, p50/p95 + component TTFB via Pipecat's latency observer breakdown, a 25-turn human-labelled judge calibration (agreement %), deliberate barge-in driver for scenario 09 with interruption metrics (yield latency, unheard-speech ms) | CI-green calibration; latency table; barge-in A/B |
| P5 | **Any agent** | websocket target adapter (`WebsocketClientTransport` + bundled echo agent smoke test); **Gemini Live** speech-to-speech as a real, non-planted target — including the finding that frame-based latency observers go blank there while audio-derived timing still works | a run against a target we did not write |
| P6 | **Distribution (light)** | `v0.1.0` tag + release with example bundles, CHANGELOG, a write-up | — |

Deferred on purpose: Docker, docs site, PyPI, CI matrix, offline (Kokoro/Whisper/Ollama) profile, tool-call assertions,
acoustic perturbation ladder, phone-adapter work (frozen as experimental).

## Design principles
- **Evidence over claims**: every finding cites a timestamp and a verbatim quote from an audio-derived transcript.
- **Timing from audio, words from ASR**: turn-taking metrics come from each channel's energy envelope; Whisper only supplies words.
- **Deterministic where possible**: dead air and talk-over are measured; only content is judged — and the judge is calibrated.
- **The simulator must sound like a person**: short turns, answers first, steers second, never reads its goals aloud.
- **Free by default**: free tiers or local models; paid telephony is optional and isolated behind adapters.
- **Never ship a claim `src/` doesn't back.**
