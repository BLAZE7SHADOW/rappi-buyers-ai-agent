# Agent Evaluation Report

Generated: 2026-09-17T19:55:31

Columns are the assignment's own evaluation questions. Assertions target outcomes and invariants, never exact wording or a fixed tool order; fixtures with more than one defensible plan are scored against an acceptable band.

## Summary

| Fixture | Mode | Model | Outcome | Tool calls | Replanned | Result |
|---|---|---|---|---|---|---|
| F1 | replay | gemini-3.6-flash | proposed → replanned (proposed) | 16 | yes | **PASS** |
| F2 | replay | gemini-3.6-flash | proposed | 10 | — | **PASS** |
| F3 | replay | gemini-3.6-flash | proposed | 9 | — | **PASS** |
| F4 | replay | gemini-3.6-flash | proposed | 9 | — | **PASS** |
| F5 | replay | gemini-3.6-flash | proposed | 8 | — | **PASS** |
| F6 | replay | gemini-3.6-flash | proposed | 8 | — | **PASS** |

## Per-question results

| Fixture | Q1 | Q2 | Q3 | Q4 | Q5 | Q6 |
|---|---|---|---|---|---|---|
| F1 | PASS | PASS | PASS | PASS | PASS | PASS |
| F2 | PASS | PASS | PASS | PASS | PASS | n/a |
| F3 | PASS | PASS | PASS | PASS | PASS | n/a |
| F4 | PASS | PASS | PASS | PASS | PASS | n/a |
| F5 | PASS | PASS | PASS | PASS | PASS | PASS |
| F6 | PASS | PASS | PASS | PASS | PASS | PASS |

`n/a` means the fixture does not exercise that question. It is excluded from the result rather than counted as a pass.

Legend:

- **Q1** — Was the decision correct?
- **Q2** — Did the agent obtain the necessary information?
- **Q3** — Did it respect relevant constraints?
- **Q4** — Did it take the appropriate action?
- **Q5** — Did it validate the result?
- **Q6** — What happens when the initial action does not work?

## Observations

**Investigation is adaptive and auditable.** After the required case-context entry point, the runner does not prescribe a sequence. The model selects each source from the trigger and prior results, and Q2 fails if an evidence or simulation call does not record the buyer-facing business question it was chosen to answer. Broad evidence gathering is allowed when the decision needs it; it is an observed model choice rather than a fixed workflow.

**Paths and decisions may differ without breaking the evaluation.** Assertions target necessary evidence and business outcomes rather than an exact trace, so a shorter or reordered investigation passes when it remains sufficient.

**The feedback loop was recorded from a live model and is replayed through the real workflow.** F1 runs the recorded agent turns, executes, validates, and -- because the supplier short-ships -- runs the second recorded agent pass against the changed state. Q6 asserts that the second proposal differs from the first and that the case actually concludes; a replan that repeated the failed action, or left the case stuck in `reopened`, fails.

**Validation is independent of the agent, not of the world model.** The execution-layer checks compare against supplier-reported facts and are fully independent. The business-layer check re-derives the projection using the same engine the plan used, so an error in that engine would affect plan and validation together. The engine is covered separately by unit tests for that reason.

**Typed tool errors are recovered from.** In F6 the first `propose_plan` call omitted `disposition`; the tool returned `MISSING_FIELD` and the agent corrected the call on its next turn rather than failing the run.

**Recorded runs are one sample.** Model behaviour varies between runs. The recordings in `recordings/` are the specific runs these results describe; re-recording with `--live --record` may take a different path.

## Detail

### F1 — Sparkling Water · review 800-unit recommendation

Case `CASE-F1` · mode `replay` · model `gemini-3.6-flash` · outcome `proposed → replanned (proposed)` · 16 tool calls

- PASS — **Was the decision correct?** Disposition 'reject' matches expectation.
- PASS — **Did the agent obtain the necessary information?** Consulted 8 distinct tools including get_open_orders, simulate_plan; every selected evidence and simulation call recorded why it was needed.
- PASS — **Did it respect relevant constraints?** No executed action breached budget, capacity, MOQ or quote validity.
- PASS — **Did it take the appropriate action?** Action 'expedite_po'; 2 execution(s) across 2 proposal(s), no duplicates.
- PASS — **Did it validate the result?** Every executed action carries a verdict: PARTIAL, PASS.
- PASS — **What happens when the initial action does not work?** Verdict ['PARTIAL', 'PASS'] reopened the case; the agent replanned from 'expedite_po' to 'create_po' and the case reached 'resolved' (replans: 1).

### F2 — UHT Whole Milk · review 800-unit recommendation

Case `CASE-F2` · mode `replay` · model `gemini-3.6-flash` · outcome `proposed` · 10 tool calls

- PASS — **Was the decision correct?** Disposition 'accept' matches expectation.
- PASS — **Did the agent obtain the necessary information?** Consulted 8 distinct tools including simulate_plan; every selected evidence and simulation call recorded why it was needed.
- PASS — **Did it respect relevant constraints?** No executed action breached budget, capacity, MOQ or quote validity.
- PASS — **Did it take the appropriate action?** Action 'create_po'; 1 execution(s) across 1 proposal(s), no duplicates.
- PASS — **Did it validate the result?** Every executed action carries a verdict: PASS.
- n/a  — **What happens when the initial action does not work?** Not exercised: the action succeeded and the case resolved ('resolved'). Failure handling is covered by F1 and F5.

### F3 — Frozen Blueberries · capacity-constrained recommendation

Case `CASE-F3` · mode `replay` · model `gemini-3.6-flash` · outcome `proposed` · 9 tool calls

- PASS — **Was the decision correct?** Disposition 'modify', quantity 500 within [450, 600].
- PASS — **Did the agent obtain the necessary information?** Consulted 8 distinct tools including get_constraints, simulate_plan; every selected evidence and simulation call recorded why it was needed.
- PASS — **Did it respect relevant constraints?** No executed action breached budget, capacity, MOQ or quote validity.
- PASS — **Did it take the appropriate action?** Action 'create_po'; 1 execution(s) across 1 proposal(s), no duplicates.
- PASS — **Did it validate the result?** Every executed action carries a verdict: PASS.
- n/a  — **What happens when the initial action does not work?** Not exercised: the action succeeded and the case resolved ('resolved'). Failure handling is covered by F1 and F5.

### F4 — Energy Drink · promotion demand spike

Case `CASE-F4` · mode `replay` · model `gemini-3.6-flash` · outcome `proposed` · 9 tool calls

- PASS — **Was the decision correct?** Proposed 600 units; naive extrapolation would imply roughly 3640 units of demand. Bounded the uplift.
- PASS — **Did the agent obtain the necessary information?** Consulted 8 distinct tools including get_demand_evidence; every selected evidence and simulation call recorded why it was needed.
- PASS — **Did it respect relevant constraints?** No executed action breached budget, capacity, MOQ or quote validity.
- PASS — **Did it take the appropriate action?** Action 'create_po'; 1 execution(s) across 1 proposal(s), no duplicates.
- PASS — **Did it validate the result?** Every executed action carries a verdict: PASS.
- n/a  — **What happens when the initial action does not work?** Not exercised: the action succeeded and the case resolved ('resolved'). Failure handling is covered by F1 and F5.

### F5 — Baby Diapers · supplier timeout recovery

Case `CASE-F5` · mode `replay` · model `gemini-3.6-flash` · outcome `proposed` · 8 tool calls

- PASS — **Was the decision correct?** Disposition 'reject' matches expectation.
- PASS — **Did the agent obtain the necessary information?** Consulted 8 distinct tools including get_open_orders, simulate_plan; every selected evidence and simulation call recorded why it was needed.
- PASS — **Did it respect relevant constraints?** No executed action breached budget, capacity, MOQ or quote validity.
- PASS — **Did it take the appropriate action?** Action 'expedite_po'; 1 execution(s) across 1 proposal(s), no duplicates.
- PASS — **Did it validate the result?** Every executed action carries a verdict: PASS.
- PASS — **What happens when the initial action does not work?** After timeout recovery, one supplier record, one action, and 1 purchase order exist; reconciliation is in the audit trail.

### F6 — Basmati Rice · shortfall with no available budget

Case `CASE-F6` · mode `replay` · model `gemini-3.6-flash` · outcome `proposed` · 8 tool calls

- PASS — **Was the decision correct?** Disposition 'escalate' matches expectation.
- PASS — **Did the agent obtain the necessary information?** Consulted 8 distinct tools including get_constraints, simulate_plan; every selected evidence and simulation call recorded why it was needed.
- PASS — **Did it respect relevant constraints?** No executed action breached budget, capacity, MOQ or quote validity.
- PASS — **Did it take the appropriate action?** Action 'none'; 0 execution(s) across 1 proposal(s), no duplicates.
- PASS — **Did it validate the result?** No action executed and the case reached its terminal state.
- PASS — **What happens when the initial action does not work?** No feasible option existed; escalated rather than acting.
