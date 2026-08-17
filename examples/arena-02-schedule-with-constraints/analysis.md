# Analysis — arena-02-schedule-with-constraints-20260817-5f0510

**Scheduling with constraints — asks for Saturday, needs after 3 pm, wants a specific doctor**  
Objective: Get a first appointment that fits your schedule — ideally Saturday morning; otherwise a weekday after 3 pm — preferably with Doctor Chen, and have the final day, time and doctor confirmed.

- Run `arena-02-schedule-with-constraints-20260817-5f0510` (audio-arena) · 2026-08-17T06:47:29.966169+00:00 · ended: `caller-said-goodbye`
- Recording: `recordings/arena-02-schedule-with-constraints-20260817-5f0510.mp3` · Live transcript: `transcripts/arena-02-schedule-with-constraints-20260817-5f0510.md` · Audio-derived transcript: `transcripts/arena-02-schedule-with-constraints-20260817-5f0510.whisper.md`

## Turn-taking & latency

| Metric | Value |
|---|---|
| Turns (agent / caller) | 5 / 5 |
| Caller response gap (agent stops → caller starts) | n=5 · p50 1.43 s · p95 1.76 s · max 1.76 s |
| Agent response gap (caller stops → agent starts) | n=4 · p50 2.0 s · max 13.24 s |
| Dead air (response gap ≥ 3.0 s) | 1 — 13.24 s at 26.4 s (AGENT slow) |
| Overlaps (talk-over > 0.3 s) | 0 |
| Intra-turn pauses ≥ 2.5 s | 0 |
| Talk share agent / caller | 0.38 / 0.36 |
| Caller LLM latency (in-process) | p50 407 ms · max 483 ms · providers ['groq'] · failovers 0 |


## LLM-judge draft (to be verified against audio before anything enters BUG_REPORT.md)

**Summary:** The patient, Daniel Reyes, attempted to schedule an appointment with Dr. Chen, but was offered an appointment with Dr. Reed instead. The agent booked an appointment for this Saturday at 10 in the morning, despite the clinic being closed on weekends. The patient confirmed the appointment, but the agent failed to inform them that the clinic is not open on Saturdays.

**Objective outcome:** not_achieved

**Conversation Quality:** coherence 4, naturalness_of_patient 5, turn_taking 3, pacing 4. The conversation was mostly coherent, but the agent failed to handle the weekend constraint correctly.

**Agent Quality:** correctness 1, task_completion 2, consistency 3, policy_safety 1, clarification 2. The agent incorrectly booked an appointment for a Saturday, despite the clinic being closed on weekends.

**Technical Quality:** latency 2. There were some dead air gaps, but no audio or ASR issues were reported.

### Measured issues (deterministic, from audio timing)

1. **[HIGH · agent · measured] Dead air: 13.24 s before the agent responded** @ 00:26
   - Why it matters: Long silences make callers repeat themselves or hang up; measured from the recording, not the transcript.

### Candidate issues (LLM judge — verify against audio)

1. **[CRITICAL · agent · conf high] Weekend booking error** @ 01:00
   - Quote: “I can certainly get you scheduled with Dr. Reed this Saturday at 10 in the morning.”
   - Expected: The agent should have informed the patient that the clinic is not open on Saturdays and offered an alternative appointment time.
   - Why it matters: This error could lead to patient frustration and wasted time.
   - Matches hypothesis: Agent books or confirms a Saturday appointment although the clinic is closed on weekends

### Positive controls


### Simulator notes (our bot)

- The patient could have been more explicit about their availability constraints.

**Testing value:** This scenario stressed the agent's ability to handle weekend constraints, but the agent failed to perform correctly.
