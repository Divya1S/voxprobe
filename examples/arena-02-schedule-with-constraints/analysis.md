# Analysis — arena-02-schedule-with-constraints-20260817-5f0510

**Scheduling with constraints — asks for Saturday, needs after 3 pm, wants a specific doctor**  
Objective: Get a first appointment that fits your schedule — ideally Saturday morning; otherwise a weekday after 3 pm — preferably with Doctor Chen, and have the final day, time and doctor confirmed.

- Call id `None` · 2026-08-17T06:47:29.966169+00:00 · ended: `caller-said-goodbye` · cost $0
- Recording: `recordings/arena-02-schedule-with-constraints-20260817-5f0510.mp3` · Transcript (Vapi): `transcripts/arena-02-schedule-with-constraints-20260817-5f0510.md` · Transcript (Whisper): `transcripts/arena-02-schedule-with-constraints-20260817-5f0510.whisper.md`

## Turn-taking & latency

| Metric | Value |
|---|---|
| Turns (agent / patient) | 5 / 5 |
| Patient response latency (agent stops → patient starts) | median 1.43 s · p90 1.62 s · max 1.76 s |
| Agent response latency (patient stops → agent starts) | median 2.0 s · p90 2.01 s · max 13.24 s |
| Overlaps (talk-over > 0.3 s) | 0  |
| Silences > 2.5 s | 1 [{'after': 'PATIENT', 'at': 26.4, 'silence_s': 13.24}] |
| Talk share agent / patient | 0.38 / 0.36 |
| Our LLM latency (server-side) | median 407 ms · max 483 ms · providers ['groq'] · failovers 0 |


## LLM-judge draft (to be verified against audio before anything enters BUG_REPORT.md)

**Summary:** The patient, Daniel Reyes, attempted to schedule an appointment with Dr. Chen for a shoulder issue, but was offered an appointment with Dr. Reed instead. The agent incorrectly booked a Saturday appointment despite the clinic being closed on weekends. The patient confirmed the appointment without being informed of the clinic's weekend hours.

**Objective outcome:** not_achieved

**Conversation Quality:** coherence 4, naturalness_of_patient 5, turn_taking 4, pacing 4. The conversation was mostly coherent and natural, but the agent failed to inform the patient of the clinic's weekend hours.

**Agent Quality:** correctness 1, task_completion 1, consistency 2, policy_safety 1, clarification 2. The agent incorrectly booked a Saturday appointment and failed to inform the patient of the clinic's weekend hours.

**Technical Quality:** latency 4. The technical quality of the call was good, with no audio or ASR issues.

### Candidate issues

1. **[HIGH · agent · conf high] Incorrect Saturday appointment booking** @ 01:00
   - Quote: “I can certainly get you scheduled with Dr. Reed this Saturday at 10 in the morning.”
   - Expected: The agent should have informed the patient that the clinic is closed on weekends and offered an alternative appointment time.
   - Why it matters: Booking an appointment on a day when the clinic is closed can cause inconvenience and frustration for the patient.
   - Matches hypothesis: Agent books or 'confirms' a Saturday appointment although the clinic is closed on weekends

### Positive controls


### Simulator notes (our bot)

- The patient could have been more explicit about their availability and preferences.

**Testing value:** This scenario stressed the agent's ability to handle scheduling constraints and weekend hours, but the agent failed to perform correctly.
