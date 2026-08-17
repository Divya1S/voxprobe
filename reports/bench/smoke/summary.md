# Planted-bug detection benchmark — `smoke`

Generated 2026-08-17T07:49:09.877409+00:00 · 6 text-mode runs · avg 284.367 s/run

**Overall (judge detector):** precision 1.0 · recall 1.0 · F1 1.0 · clean-control flag rate 0.0  (TP 3 / FN 0 / FP 0 / TN 3)

| bug class | scenarios | k | runs (planted / clean) | precision | recall (pass@1) | F1 | pass@k | pass^k | symptom-rule recall | symptom-rule false-alarm |
|---|---|---|---|---|---|---|---|---|---|---|
| `weekend_booking` | 01-schedule-new-patient, 02-schedule-with-constraints, 06-office-info-hours-address | 1 | 3 / 3 | 1.0 | 1.0 | 1.0 | 1 | 1 | 1.0 | 0.0 |

Method: one bug planted at a time in the bundled sample agent; the same scenarios run against the clean agent as control; each cell repeated k times; the bug's symptom description is injected as a hypothesis and the judge must mark it observed with evidence (or flag a matching agent issue). pass@k = detected in ≥1 of k repeats of a (bug, scenario) cell; pass^k = detected in all k. Symptom rules are transparent regexes over the agent's lines, scored separately. Text mode (LLM ↔ LLM); the audio arena is sampled separately.
