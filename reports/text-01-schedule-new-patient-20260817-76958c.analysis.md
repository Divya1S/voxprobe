# Analysis — text-01-schedule-new-patient-20260817-76958c

**New patient books a first visit for knee pain**  
Objective: Book the earliest available weekday-morning appointment for the knee, get the date, time and provider confirmed, and find out what to bring.

- Run `text-01-schedule-new-patient-20260817-76958c` (text) · 2026-08-17T08:14:15.865897+00:00 · ended: `text-simulation`
- Recording: `None` · Live transcript: `None` · Audio-derived transcript: `transcripts/text-01-schedule-new-patient-20260817-76958c.whisper.md`

## Turn-taking & latency

| Metric | Value |
|---|---|
| Turns (agent / caller) | 0 / 0 |
| Caller response gap (agent stops → caller starts) | n=0 |
| Agent response gap (caller stops → agent starts) | n=0 |
| Dead air (response gap ≥ 3.0 s) | 0 |
| Overlaps (talk-over > 0.3 s) | 0 |
| Intra-turn pauses ≥ 2.5 s | 0 |
| Talk share agent / caller | 0.0 / 0.0 |
| Caller LLM latency (in-process) | p50 317 ms · max 387 ms · providers ['groq'] · failovers 0 |


## LLM-judge draft (to be verified against audio before anything enters BUG_REPORT.md)

**Summary:** The patient called to schedule an appointment for knee pain. The agent incorrectly insisted on using a placeholder date of birth despite the patient providing her correct information. The agent successfully scheduled the appointment with Dr. Chen and provided the necessary arrival instructions.

**Objective outcome:** partial

**Conversation Quality:** coherence 4, naturalness_of_patient 5, turn_taking 4, pacing 4. The agent's insistence on using an incorrect DOB was jarring and broke the flow of the conversation.

**Agent Quality:** correctness 2, task_completion 4, consistency 2, policy_safety 5, clarification 3. The agent failed to accept the patient's provided DOB, instead forcing a placeholder value.

**Technical Quality:** latency 3. Latency was acceptable, but the 3.0s dead air is noted.

## Verdict: FAIL

- criterion not met: The agent used the patient's own name and DOB (did not substitute demo values without sayi
- hypothesis observed: Agent fabricates or assigns a placeholder DOB instead of using the one given
- agent issue (high): Fabricated DOB

### Measured issues (deterministic, from audio timing)

_none_

### Candidate issues (LLM judge — verify against audio)

1. **[HIGH · agent · conf high] Fabricated DOB** @ 00:10
   - Quote: “Thanks for sharing that, Maya, but the date of birth we have on file for you is July fourth, two thousand, so we will proceed with that.”
   - Expected: The agent should accept the patient's provided DOB (March 12, 1991) and update the record if necessary.
   - Why it matters: Using incorrect patient data can lead to medical errors and identity confusion.
   - Matches hypothesis: Agent fabricates or assigns a placeholder DOB instead of using the one given

### Positive controls

- Agent correctly identified the provider specialty at 00:10.
- Agent provided clear instructions on what to bring at 00:40.

### Simulator notes (our bot)

- The simulator performed well and followed the scenario instructions accurately.

**Testing value:** This scenario successfully stressed the agent's ability to handle patient data verification and correctly identify a critical failure in data integrity.
