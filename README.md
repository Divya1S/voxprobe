# voxprobe

**Persona-driven QA for voice agents.** Point voxprobe at a voice agent — a bundled local sample, a websocket endpoint, or (optionally)
a phone number — and it runs realistic simulated callers through test scenarios, records both sides, builds audio-timed transcripts,
measures turn-taking and latency for *both* parties, and drafts evidence-backed findings you can verify against the audio.

> Status: milestone 1 (core + text-mode local arena) is complete; the Pipecat audio arena is next. See [docs/ROADMAP.md](docs/ROADMAP.md).

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
 simulated caller ── talks to ──▶ target agent   (local sample agent · websocket · phone adapter)
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
- **Free by default.** Groq + Gemini free tiers for the LLM, Deepgram free credit or local models for speech. Phone telephony is optional.

## Quick start

```bash
git clone <your-repo-url> && cd voxprobe
cp .env.example .env          # add GROQ_API_KEY and GOOGLE_API_KEY (both free, no card)
uv sync --extra dev
uv run pytest -q

uv run voxprobe list
uv run voxprobe simulate --scenario 02 --target local-clinic-buggy      # text-mode local run
```

Requires Python ≥ 3.11, [uv](https://docs.astral.sh/uv/), and `ffmpeg` on PATH.

## Repository layout

| Path | What |
|---|---|
| `scenarios/` | 14 test scenarios (scheduling, cancellation, refills, information, ambiguity, barge-in, emergency triage, memory, language switch, slow caller, social engineering) |
| `targets/` | agents under test: `local-clinic` (clean sample), `local-clinic-buggy` (planted bugs), `example-phone-vapi` (template) |
| `src/voxprobe/` | `scenarios.py`, `targets.py`, `persona.py`, `director.py`, `brain.py` (LLM + failover), `simulate.py` (local arena), `retranscribe.py`, `metrics.py`, `analyze.py`, `evidence.py`, `server.py` + `vapi_client.py` + `call_runner.py` (phone adapter), `cli.py` |
| `recordings/ transcripts/ reports/` | evidence per run |
| `docs/` | roadmap, engineering log |

## Environment variables

See [`.env.example`](.env.example). Nothing is required beyond `GROQ_API_KEY` and `GOOGLE_API_KEY` for the local demo.
Phone adapters additionally need their provider keys and an explicit `ALLOWED_NUMBERS_E164` allow-list — voxprobe refuses to dial any
number that is not on it.

## License

MIT
