# ADR-002 — In-process loopback pair instead of a websocket harness

**Status:** accepted (2026-08-16) · **Context:** the audio arena needs a simulated caller and an agent to talk over real audio.

## Options considered
1. **Pipecat's eval harness (`pipecat.evals`)** — scripted user turns played through a virtual microphone over a websocket
   into one agent pipeline; assertions on the agent's replies. Mature, but the caller is a script: it cannot adapt to what
   the agent says, and there is no second pipeline to measure.
2. **Two pipelines over localhost websockets** (`WebsocketServerTransport` + `WebsocketClientTransport`) — works, but the
   Protobuf serializer carries only a subset of frames (bot-speaking, TTS and metrics frames are dropped), adds a socket
   and serialization to every 20 ms chunk, and still needs a silence-ticking microphone.
3. **A custom in-process loopback pair** — two `BaseInputTransport`/`BaseOutputTransport` subclasses wired directly.

## Decision
Option 3. Output paces writes like a sound card (one 20 ms chunk per 20 ms) so interruptions can still drop unplayed audio;
input is a virtual microphone ticking every 20 ms with silence between utterances (VAD needs a continuous stream — the same
insight `pipecat.evals` uses for its own mic); interruption flushes the peer's unplayed audio and reports the bytes dropped.

## Consequences
- Two full pipelines (each with its own STT/VAD/turn-taking/LLM/TTS) run in one asyncio loop with no network hop; the recorder
  in the caller pipeline captures L = agent, R = caller directly.
- The pair is ~200 lines and Pipecat-version-sensitive (1.7: `add_workers` is async, VAD lives on aggregator params); a POC
  script (`scripts/arena_poc.py`) proves pacing, turn detection and stereo capture before the full arena is used.
- A websocket *target* adapter (to test external agents) is still worthwhile and planned; this decision is about the two
  bundled pipelines, not about reaching remote agents.
