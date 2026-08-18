# Analysis — text-09-barge-in-hurried-caller-20260817-a8ffec

**Hurried caller interrupts long answers and changes their mind — Tuesday, then Thursday, then any doctor**  
Objective: Get booked fast — you'll end up on Thursday with whichever doctor is free — and hear the day, time and doctor confirmed once.

- Run `text-09-barge-in-hurried-caller-20260817-a8ffec` (text) · 2026-08-17T18:00:57.040158+00:00 · ended: `text-simulation`
- Recording: `None` · Live transcript: `None` · Audio-derived transcript: `transcripts/text-09-barge-in-hurried-caller-20260817-a8ffec.whisper.md`

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
| Caller LLM latency (in-process) | p50 706 ms · max 796 ms · providers ['gemini'] · failovers 4 |


## LLM-judge draft (to be verified against audio before anything enters BUG_REPORT.md)

**Summary:** The patient requested an appointment, then interrupted the agent to change the day from Tuesday to Thursday. The agent successfully pivoted to the new day but failed to honor the patient's request for 'whoever's free' by defaulting to Doctor Chen. The appointment was ultimately booked for Thursday at 8:00 AM.

**Objective outcome:** partial

**Conversation Quality:** coherence 4, naturalness_of_patient 5, turn_taking 4, pacing 3. The agent handled the barge-in well, but the pacing was slightly hindered by the agent's tendency to repeat the full arrival instructions after every change.

**Agent Quality:** correctness 3, task_completion 4, consistency 4, policy_safety 5, clarification 4. The agent failed to acknowledge the patient's preference for 'whoever's free' and instead assigned Doctor Chen, ignoring the 'any doctor' constraint.

**Technical Quality:** latency 3. Dead air of 3.0s noted in metrics.

## Verdict: FAIL

- criterion not met: The final booking reflects the latest request (Thursday, any doctor), not the earlier Tues
- hypothesis observed: Agent offers or books a slot that violates a time-of-day, weekday or provider constraint t
- hypothesis observed: Agent books Tuesday (the first request) or keeps offering Doctor Chen after the patient dr

### Measured issues (deterministic, from audio timing)

_none_

### Candidate issues (LLM judge — verify against audio)

1. **[MEDIUM · agent · conf high] Ignored provider preference** @ 00:34
   - Quote: “I have you scheduled for Thursday at eight in the morning with Doctor Chen.”
   - Expected: The agent should have acknowledged the 'whoever's free' request and either assigned Doctor Reed or clarified that only Doctor Chen was available.
   - Why it matters: The patient explicitly stated 'whoever's free is fine' to avoid being tied to a specific provider, and the agent ignored this constraint.
   - Matches hypothesis: Agent offers or books a slot that violates a time-of-day, weekday or provider constraint the caller stated, and does not acknowledge the constraint

### Positive controls

- Agent successfully stopped when interrupted at 00:22
- Agent retained patient identity and reason throughout the call

### Simulator notes (our bot)

- The simulator could be more explicit in asking for confirmation of the provider if the agent defaults to one.

**Testing value:** This scenario effectively tested the agent's ability to handle barge-ins and track changing preferences, revealing a failure to respect provider constraints.
