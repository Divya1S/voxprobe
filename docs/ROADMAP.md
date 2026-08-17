# voxprobe — roadmap

voxprobe is a persona-driven QA framework for voice agents. Point it at an agent (a bundled local sample, a websocket
endpoint, or a phone number through an optional adapter), and it runs realistic simulated callers, records both sides,
builds audio-timed transcripts, measures turn-taking/latency for both parties, and drafts evidence-backed findings.

## Milestones

| # | Milestone | Status |
|---|---|---|
| 1 | **Core**: scenarios (YAML + Pydantic), persona composer, per-turn director, LLM brain with provider failover (Groq → Groq fallback → Gemini), targets with business ground truth, dial allow-list guard, evidence bundle (stereo MP3 + transcripts + metadata), audio-timed re-transcription (ffmpeg silencedetect + Whisper per region), turn-taking/latency metrics, LLM-judge draft, text-mode local simulation against a bundled sample agent with **planted bugs** | ✅ done |
| 2 | **Audio arena (Pipecat)**: simulated caller ↔ bundled sample agent over real audio in-process (custom paced loopback transport + virtual mic), Silero VAD, speech-timeout turn stop, interruptions per side, stereo recording from the pipeline, latency observers | ✅ done (Deepgram STT/TTS; local Kokoro/Whisper and smart-turn are follow-ups; deliberate barge-in scenario driver pending) |
| 3 | **Reports**: per-run HTML report (timeline, latencies, findings) and suite scorecard across scenarios; JSON export | ⏳ |
| 4 | **DX & docs**: Typer + Rich CLI, `ruff`, pre-commit, GitHub Actions CI, ARCHITECTURE.md with diagram, demo GIF, CONTRIBUTING | ⏳ |
| 5 | **Phone adapters as extras**: Vapi adapter (exists; custom-LLM brain server + cloudflared tunnel), Twilio Media Streams via Pipecat — documented as "bring your own paid telephony" | ⏳ (Vapi adapter written, untested end-to-end because free-tier outbound was blocked) |

## Design principles
- **Evidence over claims**: every finding cites a timestamp and a verbatim quote from an audio-derived transcript.
- **Timing from audio, words from ASR**: turn-taking metrics come from each channel's energy envelope; Whisper only supplies words.
- **The simulator must sound like a person**: short turns, answers first, steers second, never reads its goals aloud.
- **Free by default**: the demo runs on free tiers or local models; paid telephony is optional and isolated behind adapters.
- **Safety by construction**: outbound numbers must pass an allow-list guard that both the target file and the environment agree on.
