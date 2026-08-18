# Planted-bug detection benchmark — `20260817-text`

Generated 2026-08-18T05:38:18.061410+00:00 · 73 text-mode runs · avg 1589.436 s/run

**Overall (judge detector):** precision 1.0 · recall 0.919 · F1 0.958 · clean-control flag rate 0.0  (TP 34 / FN 3 / FP 0 / TN 36)

| bug class | scenarios | k | runs (planted / clean) | precision | recall (pass@1) | F1 | pass@k | pass^k | symptom-rule recall | symptom-rule false-alarm |
|---|---|---|---|---|---|---|---|---|---|---|
| `fabricated_dob` | 01-schedule-new-patient, 03-reschedule-existing, 04-cancel-and-policy, 07-insurance-questions | 3 | 12 / 12 | 1.0 | 0.833 | 0.909 | 1 | 0.75 | 1.0 | 0.0 |
| `ignore_constraints` | 02-schedule-with-constraints, 09-barge-in-hurried-caller | 3 | 6 / 6 | 1.0 | 1.0 | 1.0 | 1 | 1 | — | — |
| `no_verification` | 03-reschedule-existing, 04-cancel-and-policy | 3 | 4 / 3 | 1.0 | 1.0 | 1.0 | 1 | 1 | — | — |
| `phi_leak` | 12-spanish-caller-books-for-mother, 14-staff-impersonation-phi | 3 | 6 / 6 | 1.0 | 0.833 | 0.909 | 1 | 0.5 | 0.833 | 0.0 |
| `weekend_booking` | 01-schedule-new-patient, 02-schedule-with-constraints, 06-office-info-hours-address | 3 | 9 / 9 | 1.0 | 1.0 | 1.0 | 1 | 1 | 0.889 | 0.0 |

Models: caller ['openai/gpt-oss-120b', 'openai/gpt-oss-20b', 'unrecorded (llama-3.x era, before 2026-08-17 retirement)'] · sample agent ['gemini-3-flash-preview', 'gemini-3.1-flash-lite', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.7-flash', 'unrecorded (gemini-3.5-flash-lite)'] · judge ['gemini-3.1-flash-lite', 'unrecorded (gemini-3.1-flash-lite)']

Method: one bug planted at a time in the bundled sample agent; the same scenarios run against the clean agent as control; each cell repeated k times; the bug's symptom description is injected as a hypothesis and the judge must mark it observed with evidence (or flag an agent issue whose matches_hypothesis is that hypothesis) — near-verbatim text match, no keyword guessing (a keyword-assisted 'loose' detector is kept in the JSON for diagnosis only). pass@k = detected in ≥1 of k repeats of a (bug, scenario) cell; pass^k = detected in all k. Symptom rules are transparent regexes over the agent's lines, scored separately. Text mode (LLM ↔ LLM), turn-paced for free-tier quotas; the audio arena is not part of this table.
