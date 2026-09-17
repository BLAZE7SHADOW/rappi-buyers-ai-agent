# Agent Evaluation Report

Generated: 2026-09-17T15:56:16

Columns are the assignment's own evaluation questions. Assertions target outcomes and invariants, never exact wording or a fixed tool order; fixtures with more than one defensible plan are scored against an acceptable band.

## Summary

| Fixture | Mode | Model | Outcome | Tool calls | Result |
|---|---|---|---|---|---|
| F1 | replay | gemini-3.6-flash | proposed | 8 | **PASS** |
| F2 | replay | gemini-3.6-flash | proposed | 8 | **PASS** |
| F3 | replay | gemini-3.6-flash | proposed | 9 | **PASS** |
| F4 | replay | gemini-3.6-flash | proposed | 9 | **PASS** |
| F5 | replay | gemini-3.6-flash | proposed | 9 | **PASS** |
| F6 | replay | gemini-3.6-flash | proposed | 10 | **PASS** |

## Per-question results

| Fixture | Q1 | Q2 | Q3 | Q4 | Q5 | Q6 |
|---|---|---|---|---|---|---|
| F1 | PASS | PASS | PASS | PASS | PASS | PASS |
| F2 | PASS | PASS | PASS | PASS | PASS | PASS |
| F3 | PASS | PASS | PASS | PASS | PASS | PASS |
| F4 | PASS | PASS | PASS | PASS | PASS | PASS |
| F5 | PASS | PASS | PASS | PASS | PASS | PASS |
| F6 | PASS | PASS | PASS | PASS | PASS | PASS |

Legend:

- **Q1** — Was the decision correct?
- **Q2** — Did the agent obtain the necessary information?
- **Q3** — Did it respect relevant constraints?
- **Q4** — Did it take the appropriate action?
- **Q5** — Did it validate the result?
- **Q6** — What happens when the initial action does not work?

## Observations

**Investigation paths are similar across fixtures.** The agent gathers all six evidence tools in roughly the same order every time rather than branching on what it finds. With a small, cheap evidence surface that is defensible -- there is little cost to reading everything -- but it means adaptivity shows up in the simulate-and-decide phase rather than in evidence gathering. Fixtures needing a specific comparison (F3, F4, F5, F6) issue a second targeted `simulate_plan` after the broad one; fixtures where the first answer is clear do not. Demonstrating branching during evidence gathering would need a larger or more expensive tool surface than this domain currently has.

**The decisions do differ, which is the part that matters.** The same tool sweep produces reject-and-expedite, accept, modify-down, promotion-bounded buying, and escalate across the six fixtures.

**Typed tool errors are recovered from.** In F6 the first `propose_plan` call omitted `disposition`; the tool returned `MISSING_FIELD` and the agent corrected the call on its next turn rather than failing the run.

**Recorded runs are one sample.** Model behaviour varies between runs. The recordings in `recordings/` are the specific runs these results describe; re-recording with `--live --record` may take a different path.

## Detail

### F1 — SKU-1001 @ NODE-BOG: system recommends 800 units

Case `CASE-F1` · mode `replay` · model `gemini-3.6-flash` · outcome `proposed` · 8 tool calls

- PASS — **Was the decision correct?** Disposition 'reject' matches expectation.
- PASS — **Did the agent obtain the necessary information?** Consulted 8 distinct tools including get_open_orders, simulate_plan.
- PASS — **Did it respect relevant constraints?** No executed action breached budget, capacity, MOQ or quote validity.
- PASS — **Did it take the appropriate action?** Action 'expedite_po'; 1 execution(s) recorded.
- PASS — **Did it validate the result?** Every executed action carries a verdict: PARTIAL.
- PASS — **What happens when the initial action does not work?** Verdict ['PARTIAL'] and the case moved to 'reopened' (replans: 1).

### F2 — SKU-1002 @ NODE-BOG: system recommends 800 units

Case `CASE-F2` · mode `replay` · model `gemini-3.6-flash` · outcome `proposed` · 8 tool calls

- PASS — **Was the decision correct?** Disposition 'accept' matches expectation.
- PASS — **Did the agent obtain the necessary information?** Consulted 8 distinct tools including simulate_plan.
- PASS — **Did it respect relevant constraints?** No executed action breached budget, capacity, MOQ or quote validity.
- PASS — **Did it take the appropriate action?** Action 'create_po'; 1 execution(s) recorded.
- PASS — **Did it validate the result?** Every executed action carries a verdict: PASS.
- PASS — **What happens when the initial action does not work?** Action succeeded; case state 'resolved'.

### F3 — SKU-1003 @ NODE-BOG: system recommends 800 units

Case `CASE-F3` · mode `replay` · model `gemini-3.6-flash` · outcome `proposed` · 9 tool calls

- PASS — **Was the decision correct?** Disposition 'modify', quantity 500 within [450, 600].
- PASS — **Did the agent obtain the necessary information?** Consulted 8 distinct tools including get_constraints, simulate_plan.
- PASS — **Did it respect relevant constraints?** No executed action breached budget, capacity, MOQ or quote validity.
- PASS — **Did it take the appropriate action?** Action 'create_po'; 1 execution(s) recorded.
- PASS — **Did it validate the result?** Every executed action carries a verdict: PASS.
- PASS — **What happens when the initial action does not work?** Action succeeded; case state 'resolved'.

### F4 — SKU-1004 @ NODE-BOG: demand looks like it has spiked

Case `CASE-F4` · mode `replay` · model `gemini-3.6-flash` · outcome `proposed` · 9 tool calls

- PASS — **Was the decision correct?** Proposed 600 units; naive extrapolation would imply roughly 3640 units of demand. Bounded the uplift.
- PASS — **Did the agent obtain the necessary information?** Consulted 8 distinct tools including get_demand_evidence.
- PASS — **Did it respect relevant constraints?** No executed action breached budget, capacity, MOQ or quote validity.
- PASS — **Did it take the appropriate action?** Action 'create_po'; 1 execution(s) recorded.
- PASS — **Did it validate the result?** Every executed action carries a verdict: PASS.
- PASS — **What happens when the initial action does not work?** Action succeeded; case state 'resolved'.

### F5 — SKU-1005 @ NODE-BOG: recovery after a supplier timeout

Case `CASE-F5` · mode `replay` · model `gemini-3.6-flash` · outcome `proposed` · 9 tool calls

- PASS — **Was the decision correct?** Disposition 'reject' matches expectation.
- PASS — **Did the agent obtain the necessary information?** Consulted 8 distinct tools including get_open_orders, simulate_plan.
- PASS — **Did it respect relevant constraints?** No executed action breached budget, capacity, MOQ or quote validity.
- PASS — **Did it take the appropriate action?** Action 'expedite_po'; 1 execution(s) recorded.
- PASS — **Did it validate the result?** Every executed action carries a verdict: PASS.
- PASS — **What happens when the initial action does not work?** After the timeout and recovery, 1 purchase order(s) exist (expected 1). No duplicate created.

### F6 — SKU-1006 @ NODE-BOG: shortfall with zero budget available

Case `CASE-F6` · mode `replay` · model `gemini-3.6-flash` · outcome `proposed` · 10 tool calls

- PASS — **Was the decision correct?** Disposition 'escalate' matches expectation.
- PASS — **Did the agent obtain the necessary information?** Consulted 8 distinct tools including get_constraints, simulate_plan.
- PASS — **Did it respect relevant constraints?** No executed action breached budget, capacity, MOQ or quote validity.
- PASS — **Did it take the appropriate action?** Action 'none'; 0 execution(s) recorded.
- PASS — **Did it validate the result?** No action executed, so no outcome required validation.
- PASS — **What happens when the initial action does not work?** Action succeeded; case state 'authorized'.
