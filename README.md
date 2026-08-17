# voxprobe

**Persona-driven QA for voice agents.** Point voxprobe at a voice agent — today the bundled local sample agents (a websocket adapter
and a Gemini Live target are on the roadmap; a Vapi phone adapter exists as an experimental extra) — and it runs realistic simulated
callers through test scenarios, records both sides, builds audio-timed transcripts, measures turn-taking and latency for *both*
parties, and drafts evidence-backed findings you can verify against the audio.

> Status: milestones 1–2 done — core, text-mode arena, and the **Pipecat audio arena** (two voice pipelines talking over an in-process virtual phone line). Next: reports & DX polish. See [docs/ROADMAP.md](docs/ROADMAP.md).

## Why

Voice agents fail in ways text evals don't catch: they book appointments on days the office is closed, invent a caller's date of birth,
talk over the caller, or go silent for three seconds. voxprobe treats the *recording* as the source of truth and makes every finding
point at a timestamp and a quote.

## What it does

```
scenarios/*.yaml  (who the caller is, what they know, what they want, what would count as a bug)
targets/*.yaml    (the agent under test + ground truth about the business it represents)
        │
        ▼
 simulated caller ── talks to ──▶ target agent   (bundled local sample agents; websocket + Gemini Live targets planned; Vapi phone adapter experimental)
   persona + per-turn director + LLM brain with failover
        │
        ▼
 evidence: stereo recording (agent L / caller R) · audio-timed transcript (Whisper per speech region)
           · turn-taking & latency metrics · LLM-judge draft with timestamps and quotes
```

- **Realistic callers, not scripts.** Each scenario is a persona (facts it may share, facts it must never invent), an objective, and an
  ordered plan; a small "director" nudges each turn ("answer their question first", "wrap up now") without scripting words.
- **Bundled sample agent with planted bugs.** `targets/local-clinic-buggy.yaml` toggles bugs like `weekend_booking`, `fabricated_dob`,
  `phi_leak` — so you can watch the framework catch them.
- **Timing from audio, words from ASR.** Speech regions per channel come from `ffmpeg silencedetect`; Whisper transcribes each region.
  Response latency, overlaps and silences are computed from the audio, for both parties.
- **Audio arena in one process.** Pipecat 1.7 ships its own eval harness (`pipecat.evals`: scripted turns played through a virtual mic over a websocket into *one* agent pipeline). voxprobe needs *two full pipelines* — an adaptive simulated caller and the agent — to talk in the same process with no socket, so it adds an in-process loopback transport pair (paced output like a sound card, virtual mic that emits silence between utterances, interruption flushes unplayed audio) and records both parties.
- **Free by default.** Groq + Gemini free tiers for the LLM, Deepgram free credit or local models for speech. Phone telephony is optional.

## Quick start

```bash
git clone https://github.com/Divya1S/voxprobe.git && cd voxprobe
cp .env.example .env          # add GROQ_API_KEY and GOOGLE_API_KEY (both free, no card)
uv sync --extra dev
uv run pytest -q

uv run voxprobe list
uv run voxprobe simulate --scenario 02 --target local-clinic-buggy               # text-mode local run (LLM ↔ LLM)

# audio arena: two Pipecat voice pipelines on a virtual phone line (needs DEEPGRAM_API_KEY — free signup credit)
uv sync --extra dev --extra arena
uv run voxprobe simulate --scenario 02 --target local-clinic-buggy --mode audio  # → MP3 + transcripts + metrics + judge
```

Requires Python ≥ 3.11, [uv](https://docs.astral.sh/uv/), and `ffmpeg` on PATH.

## Example output (real runs, in [`examples/`](examples/))

| Run | What happened | Evidence |
|---|---|---|
| [`arena-01-schedule-new-patient`](examples/arena-01-schedule-new-patient/) | clean sample agent books a first visit; 4 agent / 3 caller turns; response gaps p50 caller 1.8 s / agent 2.0 s, no overlaps; **one measured dead-air event is our own simulator's** (4.6 s, a slow LLM turn) — the instrument measures both parties; judge: no agent issues | [recording.mp3](examples/arena-01-schedule-new-patient/recording.mp3) · [transcript](examples/arena-01-schedule-new-patient/transcript.whisper.md) · [analysis](examples/arena-01-schedule-new-patient/analysis.md) |
| [`arena-02-schedule-with-constraints`](examples/arena-02-schedule-with-constraints/) | agent with planted bugs confirms a **Saturday** slot at a weekday-only clinic — a *false success* (it says booked; ground truth says no such slot) — judge flags it at 01:00 with the quote; the instrument separately measures a **13.2 s dead-air** event by the agent at 00:26 (deterministic, HIGH) | [recording.mp3](examples/arena-02-schedule-with-constraints/recording.mp3) · [transcript](examples/arena-02-schedule-with-constraints/transcript.whisper.md) · [analysis](examples/arena-02-schedule-with-constraints/analysis.md) |

Recordings are stereo: **left = agent under test, right = simulated caller** — open one in any editor and you can see the turn-taking.

## Repository layout

| Path | What |
|---|---|
| `scenarios/` | 14 test scenarios (scheduling, cancellation, refills, information, ambiguity, barge-in, emergency triage, memory, language switch, slow caller, social engineering) |
| `targets/` | agents under test: `local-clinic` (clean sample), `local-clinic-buggy` (planted bugs), `example-phone-vapi` (template for the experimental phone adapter) |
| `src/voxprobe/` | `scenarios.py`, `targets.py`, `persona.py`, `director.py`, `brain.py` (LLM + failover), `simulate.py` (text arena + sample agent prompt), `arena/` (`loopback.py` virtual phone line, `caller_brain.py` Pipecat LLM service, `run.py` audio arena), `retranscribe.py`, `metrics.py`, `analyze.py`, `evidence.py`, `server.py` + `vapi_client.py` + `call_runner.py` (phone adapter), `cli.py` |
| `examples/` | curated real runs: recording + transcripts + analysis |
| `recordings/ transcripts/ reports/` | evidence per run |
| `docs/` | roadmap, engineering log |

## Environment variables

See [`.env.example`](.env.example). Nothing is required beyond `GROQ_API_KEY` and `GOOGLE_API_KEY` for the local demo.
Phone adapters additionally need their provider keys and an explicit `ALLOWED_NUMBERS_E164` allow-list — voxprobe refuses to dial any
number that is not on it.

## License

MIT
