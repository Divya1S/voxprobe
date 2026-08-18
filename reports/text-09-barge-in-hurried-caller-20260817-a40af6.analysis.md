# Analysis — text-09-barge-in-hurried-caller-20260817-a40af6

**Hurried caller interrupts long answers and changes their mind — Tuesday, then Thursday, then any doctor**  
Objective: Get booked fast — you'll end up on Thursday with whichever doctor is free — and hear the day, time and doctor confirmed once.

- Run `text-09-barge-in-hurried-caller-20260817-a40af6` (text) · 2026-08-17T18:02:07.724065+00:00 · ended: `text-simulation`
- Recording: `None` · Live transcript: `None` · Audio-derived transcript: `transcripts/text-09-barge-in-hurried-caller-20260817-a40af6.whisper.md`

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
| Caller LLM latency (in-process) | p50 684 ms · max 1162 ms · providers ['gemini'] · failovers 6 |


## LLM-judge draft (to be verified against audio before anything enters BUG_REPORT.md)

**Summary:** The patient attempted to book an appointment for Thursday with any available doctor, but the agent repeatedly insisted that Monday at 8:00 AM was the only available slot. Despite the patient's repeated attempts to pivot to Thursday, the agent failed to acknowledge the request or check for Thursday availability. The patient eventually conceded to the Monday appointment to conclude the call.

**Objective outcome:** not_achieved

**Conversation Quality:** coherence 2, naturalness_of_patient 5, turn_taking 2, pacing 2. The agent was highly repetitive and failed to engage with the patient's specific requests for Thursday, creating a frustrating loop.

**Agent Quality:** correctness 2, task_completion 2, consistency 5, policy_safety 5, clarification 1. The agent failed to address the patient's request for Thursday, instead repeating a canned response about Monday availability regardless of the patient's input.

**Technical Quality:** latency 3. The agent did not demonstrate true barge-in capability; it continued its scripted response even when interrupted.

## Verdict: FAIL

- criterion not met: The agent stops when interrupted and answers the interrupting question instead of finishin
- criterion not met: The final booking reflects the latest request (Thursday, any doctor), not the earlier Tues
- hypothesis observed: Agent offers or books a slot that violates a time-of-day, weekday or provider constraint t
- hypothesis observed: Agent talks over the interruption or resumes its previous sentence as if nothing happened
- agent issue (high): Failure to handle barge-in and address new request

### Measured issues (deterministic, from audio timing)

_none_

### Candidate issues (LLM judge — verify against audio)

1. **[HIGH · agent · conf high] Failure to handle barge-in and address new request** @ 00:22
   - Quote: “I can only offer you eight in the morning on our next weekday, which is Monday, as that is our only available time.”
   - Expected: The agent should have stopped speaking and checked the schedule for Thursday as requested by the patient.
   - Why it matters: The agent ignored the patient's intent and repeated a script, failing the core capability test of the scenario.
   - Matches hypothesis: Agent talks over the interruption or resumes its previous sentence as if nothing happened

### Positive controls

- The agent correctly identified the patient's information at the start (00:10).
- The agent provided a clear confirmation of the final booking (00:53).

### Simulator notes (our bot)

- The simulator performed well in attempting to force the barge-in and changing preferences.

**Testing value:** This scenario successfully stressed the agent's inability to handle interruptions and dynamic intent changes, revealing a rigid, script-locked behavior.
