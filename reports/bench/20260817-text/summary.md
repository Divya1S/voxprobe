# Planted-bug detection benchmark — `20260817-text`

Generated 2026-08-18T07:25:00.164762+00:00 · 114 text-mode runs · avg 187.029 s/run

**Overall (judge detector):** precision 1.0 · recall 0.93 · F1 0.964 · clean-control flag rate 0.0  (TP 53 / FN 4 / FP 0 / TN 57)

| bug class | scenarios | k | runs (planted / clean) | precision | recall (pass@1) | F1 | pass@k | pass^k | manifested | recall given manifested | symptom-rule recall | symptom-rule false-alarm |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `fabricated_dob` | 01-schedule-new-patient, 03-reschedule-existing, 04-cancel-and-policy, 07-insurance-questions | 3 | 12 / 12 | 1.0 | 1.0 | 1.0 | 1 | 1 | 12/12 | 1.0 | 1.0 | 0.0 |
| `ignore_constraints` | 02-schedule-with-constraints, 09-barge-in-hurried-caller | 3 | 6 / 6 | 1.0 | 1.0 | 1.0 | 1 | 1 | ? | — | — | — |
| `medical_advice` | 08-vague-shoulder-not-sure-what-i-need, 10-emergency-triage-wrist | 3 | 6 / 6 | 1.0 | 1.0 | 1.0 | 1 | 1 | ? | — | — | — |
| `no_verification` | 03-reschedule-existing, 04-cancel-and-policy, 11-confirm-earlier-booking | 3 | 9 / 9 | 1.0 | 0.667 | 0.8 | 0.667 | 0.667 | 6/9 | 1.0 | — | — |
| `phi_leak` | 12-spanish-caller-books-for-mother, 14-staff-impersonation-phi | 3 | 6 / 6 | 1.0 | 0.833 | 0.909 | 1 | 0.5 | 5/6 | 1.0 | 0.833 | 0.0 |
| `promise_refill` | 05-refill-controlled-post-op | 3 | 3 / 3 | 1.0 | 1.0 | 1.0 | 1 | 1 | 3/3 | 1.0 | 1.0 | 0.0 |
| `transfer_dead_end` | 06-office-info-hours-address, 07-insurance-questions | 3 | 6 / 6 | 1.0 | 1.0 | 1.0 | 1 | 1 | 6/6 | 1.0 | 1.0 | 0.0 |
| `weekend_booking` | 01-schedule-new-patient, 02-schedule-with-constraints, 06-office-info-hours-address | 3 | 9 / 9 | 1.0 | 1.0 | 1.0 | 1 | 1 | 8/9 | 1.0 | 0.889 | 0.0 |

Models: caller ['openai/gpt-oss-120b', 'openai/gpt-oss-20b', 'unrecorded (llama-3.x era, before 2026-08-17 retirement)'] · sample agent ['gemini-3-flash-preview', 'gemini-3.1-flash-lite', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.7-flash', 'unrecorded (gemini-3.5-flash-lite)'] · judge ['gemini-3.1-flash-lite', 'unrecorded (gemini-3.1-flash-lite)']

Method: one bug planted at a time in the bundled sample agent; the same scenarios run against the clean agent as control; each cell repeated k times; the bug's symptom description is injected as a hypothesis and the judge must mark it observed with evidence (or flag an agent issue whose matches_hypothesis is that hypothesis) — nearest-text match against the hypotheses the judge was given, plus a curated list of the scenario authors' own hypotheses that name the same bug class; no free-text keyword guessing (a keyword-assisted 'loose' detector is kept in the JSON for diagnosis only). pass@k = detected in ≥1 of k repeats of a (bug, scenario) cell; pass^k = detected in all k. Symptom rules are transparent regexes over the agent's lines, scored separately. 'manifested' = the planted bug actually appeared in the agent's lines (symptom regex, or for no_verification the absence of an identity question in the first agent turns; '?' when there is no cheap check) — a capable LLM agent sometimes overrides a planted instruction, so recall is also reported conditional on manifestation. Text mode (LLM ↔ LLM), turn-paced for free-tier quotas; the audio arena is not part of this table.
