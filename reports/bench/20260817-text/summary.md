# Planted-bug detection benchmark — `20260817-text`

Generated 2026-08-17T18:14:05.910539+00:00 · 51 text-mode runs · avg 1916.459 s/run

**Overall (judge detector):** precision 1.0 · recall 1.0 · F1 1.0 · clean-control flag rate 0.0  (TP 26 / FN 0 / FP 0 / TN 25)

| bug class | scenarios | k | runs (planted / clean) | precision | recall (pass@1) | F1 | pass@k | pass^k | symptom-rule recall | symptom-rule false-alarm |
|---|---|---|---|---|---|---|---|---|---|---|
| `fabricated_dob` | 01-schedule-new-patient, 03-reschedule-existing, 04-cancel-and-policy, 07-insurance-questions | 3 | 11 / 12 | 1.0 | 1.0 | 1.0 | 1 | 1 | 1.0 | 0.0 |
| `ignore_constraints` | 02-schedule-with-constraints, 09-barge-in-hurried-caller | 3 | 6 / 4 | 1.0 | 1.0 | 1.0 | 1 | 1 | — | — |
| `weekend_booking` | 01-schedule-new-patient, 02-schedule-with-constraints, 06-office-info-hours-address | 3 | 9 / 9 | 1.0 | 1.0 | 1.0 | 1 | 1 | 0.889 | 0.0 |

Method: one bug planted at a time in the bundled sample agent; the same scenarios run against the clean agent as control; each cell repeated k times; the bug's symptom description is injected as a hypothesis and the judge must mark it observed with evidence (or flag a matching agent issue). pass@k = detected in ≥1 of k repeats of a (bug, scenario) cell; pass^k = detected in all k. Symptom rules are transparent regexes over the agent's lines, scored separately. Text mode (LLM ↔ LLM); the audio arena is sampled separately.
