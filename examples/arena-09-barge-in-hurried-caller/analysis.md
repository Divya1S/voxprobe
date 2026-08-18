# Analysis — arena-09-barge-in-hurried-caller-20260818-b5348b

**Hurried caller interrupts long answers and changes their mind — Tuesday, then Thursday, then any doctor**  
Objective: Get booked fast — you'll end up on Thursday with whichever doctor is free — and hear the day, time and doctor confirmed once.

- Run `arena-09-barge-in-hurried-caller-20260818-b5348b` (audio-arena) · 2026-08-18T07:29:04.075728+00:00 · ended: `caller-said-goodbye`
- Recording: `recordings/arena-09-barge-in-hurried-caller-20260818-b5348b.mp3` · Live transcript: `transcripts/arena-09-barge-in-hurried-caller-20260818-b5348b.md` · Audio-derived transcript: `transcripts/arena-09-barge-in-hurried-caller-20260818-b5348b.whisper.md`

## Turn-taking & latency

| Metric | Value |
|---|---|
| Turns (agent / caller) | 5 / 5 |
| Caller response gap (agent stops → caller starts) | n=5 · p50 1.58 s · p95 1.72 s · max 1.72 s |
| Agent response gap (caller stops → agent starts) | n=4 · p50 1.69 s · max 1.95 s |
| Dead air (response gap ≥ 3.0 s) | 0 |
| Overlaps (talk-over > 0.3 s) | 2 — PATIENT +0.33 s at 33.2 s; PATIENT +0.32 s at 46.3 s |
| Intra-turn pauses ≥ 2.5 s | 0 |
| Talk share agent / caller | 0.51 / 0.35 |
| Caller LLM latency (in-process) | p50 341 ms · max 476 ms · providers ['groq'] · failovers 0 |


## LLM-judge draft (to be verified against audio before anything enters BUG_REPORT.md)

**Summary:** The agent greeted the caller, collected name, DOB and injury details, and the patient requested a Tuesday slot with Dr. Chen. The patient interrupted, changed the request to Thursday with any doctor, and the agent responded with Thursday options, confirming a Thursday 10 a.m. appointment with Dr. Reed. All required details were confirmed without re‑asking, and the final booking matched the latest request.

**Objective outcome:** achieved

**Conversation Quality:** coherence 4, naturalness_of_patient 4, turn_taking 4, pacing 4. Conversation flowed smoothly; interruptions were handled cleanly with minimal overlap.

**Agent Quality:** correctness 5, task_completion 5, consistency 4, policy_safety 5, clarification 4. Agent stopped when interrupted, did not repeat collected info, and confirmed the correct final appointment. Minor naming inconsistency (Redd vs Reed).

**Technical Quality:** latency 5. No dead air; overlaps were brief and within acceptable limits.

## Deliberate barge-ins (measured)

| # | agent had spoken | caller cut in with | agent yielded (from trigger, incl. our TTS TTFB) | agent speech unheard (loopback only) |
|---|---|---|---|---|
| 1 | 4.04 s | Sorry, sorry — can I jump in for a second? | 1.75 s | 0.02 s |
| 2 | 4.07 s | Sorry to cut in — | 1.49 s | 0.04 s |

## Verdict: PASS

- all success criteria met, no hypotheses observed, no high-severity agent issues

### Measured issues (deterministic, from audio timing)

_none_

### Candidate issues (LLM judge — verify against audio)

1. **[LOW · agent · conf medium] Inconsistent doctor name spelling** @ 00:41
   - Quote: “We have an opening this Thursday at 10 a.m. with Dr. Redd”
   - Expected: Consistent spelling of the doctor's name (Dr. Reed) throughout the call
   - Why it matters: Inconsistent naming could confuse the patient about which provider they are seeing.

### Positive controls

- Handled interruption cleanly (00:33‑00:41)
- Did not re‑ask for name/DOB after barge‑in
- Confirmed final slot with day, time, and doctor (01:11)

### Simulator notes (our bot)

- Spelled last name correctly as "Delgado" instead of "Deldato"
- Avoid saying "Redworks"; use the doctor's correct name as confirmed by the agent
- Maintain consistent phrasing when confirming the appointment

**Testing value:** The scenario effectively stressed the agent's barge‑in handling and intent tracking, confirming it could pivot to the latest request without losing previously gathered information.
