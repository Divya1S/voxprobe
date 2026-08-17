# Engineering log

Chronological, evidence-based notes on what was measured, what broke, and what changed. Newest at the bottom.

## 2026-08-16 — v0: brain, scenarios, evidence pipeline (local, no telephony)

**Prompt budget is a real-time constraint.** The persona prompt is re-sent every turn; free-tier LLMs cap tokens per minute.
Measured Groq limits from response headers (not docs): `llama-3.1-8b-instant` 6K TPM, `openai/gpt-oss-20b` 8K, `llama-3.3-70b-versatile` 12K.
Text simulations showed prompt tokens growing 636 → 992 across a call (history window 10) ≈ 5.4–6.0K tokens/min at a brisk 7 turns/min.
→ Chose 70B as primary (2× headroom, ~380 ms), 8B as a second Groq bucket, Gemini as failover.

**Simulator issues found in text mode, fixed before spending anything:** the caller skipped a plan step when the agent jumped
ahead (→ "do each step before moving on"); one reply echoed the objective's wording verbatim (→ "never read your goals or plan aloud");
the composed prompt was ~650 est. tokens (→ tightened speech rules and boundaries).

**Model drift is real:** `gemini-2.5-flash-lite` returned 404 "no longer available to new users" → picked `gemini-3.5-flash-lite` from the
models API rather than memory.

**YAML gotchas:** unquoted `1991-03-12` parses to a `date` (fixed in the schema, not by quoting data); a colon-space inside a plain scalar
turns it into a nested key (quote such strings).

**Transcription: timing from audio, words from Whisper.** A synthetic stereo call (macOS `say`, agent left / caller right, scripted gaps,
one deliberate overlap, one 3.2 s silence) exposed that Whisper on a whole channel with long silences drifts and drops lines. Rewrote the
transcriber to derive speech regions per channel with `ffmpeg silencedetect`, transcribe each region as its own clip, and stamp it with the
region's start. Result: all 9 utterances recovered; scripted response gaps 0.8/0.7/0.9 s measured 0.88/0.91/1.04 s; the 3.2 s silence detected
as 3.25 s; the deliberate overlap detected as 0.51 s. The judge then flagged the planted "Sunday at nine" offer.

**Judge needs ground truth.** Without knowing the business is closed on weekends, the judge rated a Sunday booking as "didn't accommodate
preference" (medium). Targets now carry business ground truth (hours, providers, policies) that the judge treats as fact.

**Tunnel lesson (phone adapter):** cloudflared quick tunnels print their URL before the connection is registered and can take ~80 s to become
routable; the runner now waits for "Registered tunnel connection" and polls `/health` for up to 120 s. Round-trip through the tunnel added
≈185 ms on top of the LLM.
