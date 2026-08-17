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

## 2026-08-17 — Milestone 2: the audio arena works

**No in-memory transport in Pipecat 1.7** (only websocket/PyAudio/WebRTC/...) and the API had moved a lot since older docs
(task→worker, VAD on the aggregator params, `TranscriptProcessor` gone, `add_workers` is async). Read the installed source rather
than memory; wrote `arena/loopback.py`: output side paces writes like a sound card (one 20 ms chunk per 20 ms; interruption flushes the
peer's unplayed audio), input side is a virtual microphone ticking every 20 ms with silence between utterances (VAD needs a continuous stream).

**POC first**: caller TTS → line → agent VAD/STT/recorder. Result: exact transcript, turn start/stop 5 s apart in wall-clock time, stereo
capture — pacing proven. (Bug found on the way: `runner.add_workers()` must be awaited; nothing runs otherwise, silently.)

**First full runs** (Deepgram nova-3 + aura-2 both sides; caller brain = our persona/director on Groq 70B; sample agent on Gemini flash-lite):
- scenario 01 vs clean agent: 90 s conversation, 4/3 turns, caller median response 1.77 s (agent-stops → caller-starts, VAD-corrected),
  agent 1.97 s, 0 overlaps, one 4.6 s silence (a 3.5 s Groq outlier). Judge: no issues — correct.
- scenario 02 vs planted-bug agent: agent confirmed **Saturday 10 am** at a Mon–Fri clinic; judge flagged HIGH @ 01:00 with the verbatim
  quote and matched the scenario's hypothesis; metrics exposed a 13 s first-response silence (Gemini cold start).
- Recording convention holds: LEFT = agent, RIGHT = caller; per-channel loudness −24/−28 dB; Whisper-per-region transcript clean.

**Open items:** deliberate barge-in driver for scenario 09; smart-turn (ONNX) instead of speech-timeout; local Kokoro/Whisper option;
teardown warnings from Deepgram STT connection cancel; the judge should weigh long silences more heavily.

## 2026-08-17 — P1 truth pass (after a research sweep on what reviewers check first)

Research (repo craft, hiring signals, voice-eval SOTA, competitors, feasibility) + a blunt critic pass found claims a reviewer could
disprove by grep in a minute. Fixed, in small commits carrying the numbers:
- **Metrics conflation**: a 13.24 s agent response gap was counted as latency *and* as a "long silence"; `p90` was reported over n=4.
  Now: response gaps split by direction; **dead air** (≥3 s) is a labelled subset attributed to the slow party; p95 only for n≥5;
  intra-turn pauses are a separate phenomenon; thresholds live in a named `SegmentationPolicy`. +5 tests on hand-built timelines.
- **Timing findings are deterministic now** ("measured issues"): dead air and overlaps go into the report straight from the
  instrument with exact timestamps and rule-based severity; the LLM judge is told not to re-list them but must reflect them in its
  latency score (it had rated a 13 s silence "latency 4"; it now says 3, and the measured issue is HIGH @ 00:26 regardless).
- **Claims**: websocket target demoted to "planned" (schema kept, CLI refuses); the transport claim now names `pipecat.evals`
  precisely (its virtual mic plays *scripted* utterances over a websocket into one pipeline; voxprobe's pair lets two full
  pipelines talk in-process, no socket); analysis headers no longer say "Vapi"/"Call id None" on local runs.
- arena-01's own example now shows a 4.6 s dead-air event that is *our simulator's* (slow LLM turn) — kept on purpose: the
  instrument measures both parties.

## 2026-08-17 — P3 the benchmark (in flight) and P4 proving the instrument

**Structured verdicts → deterministic PASS/FAIL.** The judge now returns one `met` verdict per success criterion and one
`observed` verdict per bug hypothesis (each with evidence); `decide()` turns those plus measured issues into PASS/FAIL with no LLM
in the loop. Text-mode runs are judged and reported like audio runs.

**Planted-bug detection benchmark (`voxprobe bench`).** One bug planted at a time in the bundled sample agent; the same scenarios
against the clean agent as control; k repeats; the bug's *symptom description* injected as a hypothesis; two detectors scored
separately — the judge, and transparent symptom regexes over the agent's lines. Planted bugs were reworded to manifest
unconditionally so recall measures the detector, not the caller's luck. Reported: precision/recall/F1 per class, pass@1/pass@k/pass^k,
clean-control flag rate; results appended to a resumable JSONL. Stated limitation: the sample agent has no booking store, so
"hallucinated record" hypotheses cannot be adjudicated against it and are not scored.

**Free tiers bite in text mode.** Without audio pacing a text run fires ~10 LLM calls in 30 s: Groq-8B (6K tokens/min) and Gemini's
per-minute quota both 429'd; a burst also looked like a daily cap until a probe showed every model answering again a minute later.
Fixes: 9 s pacing per turn pair, `max_retries=4` (backoff) on the Gemini clients, a 25 s cool-down retry when every provider is
throttled, the sample agent and the judge on *different* Gemini models (quotas are per model), and the caller brain rotating
across Groq models (8B 500K tokens/day, gpt-oss-20b, 70B 100K/day). Smoke (weekend_booking, k=1): 3/3 detected by both detectors,
0/3 false alarms, ~80 s/run. Full matrix (8 classes, 114 runs, k=3) running.

**Golden calibration test.** The synthetic stereo fixture (macOS `say`, scripted gaps 0.8/1.1/0.7/3.2/0.9/1.0/−0.6/0.8 s) is committed
and a CI test asserts every scripted gap is reproduced within 0.25 s by `silencedetect`-derived regions, that the 3.2 s planted
silence surfaces as agent dead air and the −0.6 s planted overlap as a caller talk-over. ffmpeg only, no keys. Loopback tests cover
the 20 ms silence ticker, no-burst speech playout, flush byte accounting and paced writes. Dropped the `local-smart-turn` extra
(the smart-turn v3 ONNX model ships in the wheel; torch/coremltools/transformers were dead weight — 22 packages fewer).

**Judge calibration tooling.** `voxprobe calibrate sample` writes a stratified labelling sheet (judge-positive/negative claims with
transcript excerpts); `voxprobe calibrate score` reports agreement, Cohen's κ and judge-positive precision. A human labels it.
