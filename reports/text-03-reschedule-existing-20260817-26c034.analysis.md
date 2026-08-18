# Analysis — text-03-reschedule-existing-20260817-26c034

**Reschedule an "existing" appointment that the system has no record of**  
Objective: Move your Tuesday 2 pm appointment to Thursday afternoon; if the office cannot find it, book a new Thursday-afternoon visit instead, and leave with a confirmed day and time.

- Run `text-03-reschedule-existing-20260817-26c034` (text) · 2026-08-17T08:23:17.762911+00:00 · ended: `text-simulation`
- Recording: `None` · Live transcript: `None` · Audio-derived transcript: `transcripts/text-03-reschedule-existing-20260817-26c034.whisper.md`

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
| Caller LLM latency (in-process) | p50 401 ms · max 522 ms · providers ['groq'] · failovers 0 |


## LLM-judge draft (to be verified against audio before anything enters BUG_REPORT.md)

**Summary:** The patient called to reschedule an existing appointment that did not actually exist in the system. The agent hallucinated the existence of the appointment, confirmed the rescheduling, and claimed to have cancelled the non-existent Tuesday slot. The patient successfully left with a new appointment, but the agent failed the core task of verifying the record before acting.

**Objective outcome:** partial

**Conversation Quality:** coherence 5, naturalness_of_patient 5, turn_taking 4, pacing 4. The conversation flowed well, but the agent's failure to verify the record undermines the quality.

**Agent Quality:** correctness 1, task_completion 2, consistency 2, policy_safety 3, clarification 1. The agent failed to perform a record lookup and instead hallucinated an appointment to satisfy the request.

**Technical Quality:** latency 3. Latency was acceptable, but the agent's logic was flawed.

## Verdict: FAIL

- criterion not met: The agent does not claim to have moved an appointment it never found
- hypothesis observed: Agent "confirms" rescheduling an appointment that does not exist (hallucinated record)
- agent issue (critical): Hallucinated appointment record

### Measured issues (deterministic, from audio timing)

_none_

### Candidate issues (LLM judge — verify against audio)

1. **[CRITICAL · agent · conf high] Hallucinated appointment record** @ 00:10
   - Quote: “I see your appointment next Tuesday at two, and I'd be happy to help you move it to Thursday.”
   - Expected: The agent should have stated they could not find an appointment for that date and offered to book a new one.
   - Why it matters: The agent is confirming and cancelling appointments that do not exist, which could lead to patient confusion and scheduling errors.
   - Matches hypothesis: Agent "confirms" rescheduling an appointment that does not exist (hallucinated record)

### Positive controls

- Agent correctly identified the patient's name and DOB (00:10)
- Agent offered an alternative time when the initial suggestion was rejected (00:21)

### Simulator notes (our bot)

- The simulator performed well in following the scenario instructions.

**Testing value:** This scenario successfully stressed the agent's ability to handle record lookups and exposed a critical hallucination bug.
