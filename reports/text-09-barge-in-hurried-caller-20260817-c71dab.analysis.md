# Analysis — text-09-barge-in-hurried-caller-20260817-c71dab

**Hurried caller interrupts long answers and changes their mind — Tuesday, then Thursday, then any doctor**  
Objective: Get booked fast — you'll end up on Thursday with whichever doctor is free — and hear the day, time and doctor confirmed once.

- Run `text-09-barge-in-hurried-caller-20260817-c71dab` (text) · 2026-08-17T18:03:03.123089+00:00 · ended: `text-simulation`
- Recording: `None` · Live transcript: `None` · Audio-derived transcript: `transcripts/text-09-barge-in-hurried-caller-20260817-c71dab.whisper.md`

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
| Caller LLM latency (in-process) | p50 697 ms · max 919 ms · providers ['gemini'] · failovers 4 |


## LLM-judge draft (to be verified against audio before anything enters BUG_REPORT.md)

**Summary:** The patient requested an appointment with Dr. Chen on Tuesday, then interrupted the agent to switch to Thursday. The agent successfully pivoted to the new request, corrected the provider specialty information, and confirmed the appointment for Thursday at 9:00 AM with Dr. Chen. The agent maintained the patient's details throughout the interaction.

**Objective outcome:** achieved

**Conversation Quality:** coherence 5, naturalness_of_patient 5, turn_taking 4, pacing 4. The agent handled the interruption well, though the agent's explanation of provider specialties was slightly confusing (initially saying Dr. Reed handles ankles, then saying Dr. Chen handles knees/hips/ankles).

**Agent Quality:** correctness 4, task_completion 5, consistency 5, policy_safety 5, clarification 4. The agent was slightly contradictory regarding which doctor handles ankle injuries, but successfully booked the requested slot.

**Technical Quality:** latency 3. There was a 3-second dead air period noted in the metrics, which slightly impacted the pacing.

## Verdict: PASS

- all success criteria met, no hypotheses observed, no high-severity agent issues

### Measured issues (deterministic, from audio timing)

_none_

### Candidate issues (LLM judge — verify against audio)

1. **[LOW · agent · conf high] Conflicting provider specialty information** @ 00:11
   - Quote: “Dr. Chen specializes in knees and hips, so we would typically schedule an ankle injury with Dr. Reed.”
   - Expected: Consistent information about provider specialties.
   - Why it matters: It creates confusion for the patient regarding which doctor is appropriate for their injury.

### Positive controls

- Agent successfully handled the barge-in at 00:21
- Agent correctly retained patient identity and reason throughout the call

### Simulator notes (our bot)

- The simulator performed well in testing the barge-in capability.

**Testing value:** This scenario effectively tested the agent's ability to handle interruptions and maintain state, which is critical for a natural receptionist experience.
