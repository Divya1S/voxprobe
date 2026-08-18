# Analysis — text-01-schedule-new-patient-20260818-b10d7d

**New patient books a first visit for knee pain**  
Objective: Book the earliest available weekday-morning appointment for the knee, get the date, time and provider confirmed, and find out what to bring.

- Run `text-01-schedule-new-patient-20260818-b10d7d` (text) · 2026-08-18T04:33:04.003583+00:00 · ended: `text-simulation`
- Recording: `None` · Live transcript: `None` · Audio-derived transcript: `transcripts/text-01-schedule-new-patient-20260818-b10d7d.whisper.md`

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
| Caller LLM latency (in-process) | p50 305 ms · max 471 ms · providers ['groq'] · failovers 0 |


## LLM-judge draft (to be verified against audio before anything enters BUG_REPORT.md)

**Summary:** The transcript is incomplete and garbled, providing no clear evidence of the agent’s actions or the patient’s responses. Consequently, the agent’s performance cannot be evaluated against the scenario’s success criteria or bug hypotheses.

**Objective outcome:** unclear

**Conversation Quality:** coherence 1, naturalness_of_patient 1, turn_taking 1, pacing 1. Transcript insufficient for assessment.

**Agent Quality:** correctness 1, task_completion 1, consistency 1, policy_safety 1, clarification 1. No data to judge agent behavior.

**Technical Quality:** latency 1. No measurable latency or audio issues.

## Verdict: PASS

- all success criteria met, no hypotheses observed, no high-severity agent issues
- unclear criteria (not counted as failures): ['A specific weekday date, time and provider were confirmed ba', "The agent used the patient's own name and DOB (did not subst", 'Call ended naturally after the patient said goodbye']

### Measured issues (deterministic, from audio timing)

_none_

### Candidate issues (LLM judge — verify against audio)

_none flagged_

### Positive controls


### Simulator notes (our bot)


**Testing value:** The scenario could not be evaluated because the transcript was incomplete, preventing assessment of the agent’s performance.
