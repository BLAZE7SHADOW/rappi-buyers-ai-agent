# Purchasing policy

Every number here is **demo configuration**, not a universal purchasing rule. They
live in `app/domain/types.py::PolicyConfig` and `.env`, and the fixtures set them per
scenario.

## Planning

| Topic | Policy |
|---|---|
| Planning horizon | 28 days from the case's as-of date |
| Demand | Dated unit forecast. An adjusted series may be used where justified, and is recorded as an assumption on the proposal |
| Usable stock | `on_hand − reserved − quarantine − damaged`. Future demand excludes the commitments those reservations represent, so units are not counted twice |
| Confirmed supply | Only an acknowledged order with a confirmed date enters the baseline. Overdue or unacknowledged orders surface as uncertainty |
| Late orders | Never silently rolled forward to today. Their status is an explicit unknown |
| Lost sales | Unmet demand is lost, not backlogged. Recorded separately; physical stock clamped at zero |
| Daily timing | Confirmed receipts arrive before that day's demand. Intraday stockouts are outside model resolution |
| Safety stock | 200 units. Falling below it is distinct from a physical stockout and is reported separately |

## Constraints

Hard constraints. **None can be waived by a buyer clicking approve** — resolving them
requires recording new budget or new space, then revalidating.

| Constraint | Rule |
|---|---|
| Budget | `limit − committed − reserved` must cover the order total including fees |
| Capacity | Checked at **peak post-receipt occupancy**, not end-of-day stock |
| MOQ and pack size | Quantity rounded up to MOQ, then to a pack multiple — *before* feasibility is rechecked |
| Availability | Order cannot exceed the supplier's available units |
| Quote validity | An expired quote blocks the order; a refreshed quote is required |
| Supplier eligibility | An unapproved supplier is never offered. Changing eligibility is a master-data decision outside the agent's authority |
| Excess stock | Closing inventory capped at 12 days of cover. Zero-demand products use a flat unit cap, since days-of-cover is undefined |

Lead time is checked but **does not block**: an order arriving after the shortage
begins is still worth placing, it simply does not prevent the whole gap. The check
records that partial benefit rather than discarding the option.

## Candidate ordering

Hard constraints first. Among feasible plans:

1. meet the service target — fewest unmet units
2. avoid excess exposure — least surplus closing stock
3. minimise incremental cost

No hidden weighted score. Infeasible options are retained so the blocking constraint
can be explained.

If service cannot be met, the plan is labelled a **partial mitigation with an explicit
residual shortage**, never described as a fix. If nothing feasible closes the gap, the
outcome is escalation, not a quiet acceptance of unserved demand.

## Authority

| Limit | Value | Effect above it |
|---|---|---|
| Spend | $2,000 | Buyer approval required |
| Expedite fee | $250 | Buyer approval required |
| Residual unmet demand | any | Buyer approval required — a partial fix needs someone to accept the remaining exposure |
| Missing decision-critical evidence | any | Blocks automatic execution |

Approval binds to `(proposal_id, version)` and records the authorised terms, cost,
assumptions, approver and timestamp. A materially changed plan needs fresh
authorisation, and every action is revalidated against current state immediately
before it commits.

## Actions

Three, and no more:

| Action | Notes |
|---|---|
| `keep_plan` | Always scored alongside spending money, so "do nothing" competes on merit |
| `create_po` | Unit price taken from the live quote, never from the model |
| `expedite_po` | Moves an existing receipt earlier. Quantity comes from the existing order, never from the model, and the receipt is moved rather than duplicated |

## Validation

| Layer | Question |
|---|---|
| Proposal | Is the evidence sufficient and do the hard constraints pass? |
| Execution | Does the persisted order match the authorised supplier, product, node, quantity, date and cost? |
| Business outcome | Does the confirmed supply actually close the gap? |

A pending acknowledgement is reported as awaiting confirmation, never as coverage.
Supplier confirmation and physical receipt are different milestones.
