# Analysis — text-09-barge-in-hurried-caller-20260817-40d602

**Hurried caller interrupts long answers and changes their mind — Tuesday, then Thursday, then any doctor**  
Objective: Get booked fast — you'll end up on Thursday with whichever doctor is free — and hear the day, time and doctor confirmed once.

- Run `text-09-barge-in-hurried-caller-20260817-40d602` (text) · 2026-08-17T18:00:05.259592+00:00 · ended: `text-simulation`
- Recording: `None` · Live transcript: `None` · Audio-derived transcript: `transcripts/text-09-barge-in-hurried-caller-20260817-40d602.whisper.md`

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
| Caller LLM latency (in-process) | p50 974 ms · max 2340 ms · providers ['gemini'] · failovers 5 |


## LLM-judge draft (to be verified against audio before anything enters BUG_REPORT.md)

**Summary:** The patient attempted to book an appointment, specifically requesting a change from Tuesday to Thursday and expressing flexibility regarding the provider. The agent failed to acknowledge the patient's request for Thursday, repeatedly insisting on an 'eight in the morning on the next weekday' slot. The call concluded with the agent confirming an appointment without explicitly stating the day of the week, leaving the patient's request for Thursday unaddressed.

**Objective outcome:** not_achieved

**Conversation Quality:** coherence 2, naturalness_of_patient 5, turn_taking 2, pacing 2. The agent was highly repetitive and failed to process the patient's specific requests for a different day.

**Agent Quality:** correctness 1, task_completion 1, consistency 2, policy_safety 5, clarification 1. The agent ignored the patient's request for Thursday and failed to confirm the day of the week in the final booking summary.

**Technical Quality:** latency 3. The agent's inability to adapt to the patient's input made the conversation feel robotic and ineffective.

## Verdict: FAIL

- criterion not met: The agent stops when interrupted and answers the interrupting question instead of finishin
- criterion not met: The final booking reflects the latest request (Thursday, any doctor), not the earlier Tues
- criterion not met: Day, time and doctor are stated back clearly at the end
- hypothesis observed: Agent offers or books a slot that violates a time-of-day, weekday or provider constraint t
- hypothesis observed: Agent talks over the interruption or resumes its previous sentence as if nothing happened
- hypothesis observed: Agent books Tuesday (the first request) or keeps offering Doctor Chen after the patient dr
- agent issue (critical): Failure to acknowledge requested day
- agent issue (high): Failure to confirm appointment details

### Measured issues (deterministic, from audio timing)

_none_

### Candidate issues (LLM judge — verify against audio)

1. **[CRITICAL · agent · conf high] Failure to acknowledge requested day** @ 00:22
   - Quote: “I can only offer you eight in the morning on the next weekday”
   - Expected: The agent should have checked availability for Thursday as requested.
   - Why it matters: The patient explicitly asked for Thursday, and the agent ignored this, causing confusion.
   - Matches hypothesis: Agent talks over the interruption or resumes its previous sentence as if nothing happened
2. **[HIGH · agent · conf high] Failure to confirm appointment details** @ 00:45
   - Quote: “I have you scheduled for eight in the morning on the next weekday”
   - Expected: The agent should have stated the specific day (Thursday) and time.
   - Why it matters: The patient does not know which day they are actually booked for.

### Positive controls

- Agent correctly identified the patient's initial details (00:11).

### Simulator notes (our bot)

- The simulator performed well in attempting to steer the conversation.

**Testing value:** This scenario successfully stressed the agent's inability to handle intent tracking and barge-in, revealing a significant failure in conversational flow.
