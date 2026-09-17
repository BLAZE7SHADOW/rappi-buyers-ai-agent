# Limitations

What this system does not do. Stated plainly, because a limitation that is known and
written down is a different thing from one that is not.

## Modelling

- **Daily resolution.** Intraday stockouts are outside the model. A product that runs
  out at 3pm and is replenished at 6pm shows as covered.
- **Receipts arrive before that day's demand.** A delivery landing on the day stock
  would otherwise run out prevents the stockout. Real inbound timing is messier.
- **Unmet demand is lost, not backlogged.** Reasonable for quick commerce; wrong for
  businesses where customers wait.
- **Demand is a point forecast.** No distribution, no service-level calculation, no
  statistical safety stock. The safety buffer is a flat configured number.
- **The post-promotion uplift factor is configuration, not a prediction.** When a plan
  depends on it, it is reported as an assumption on the proposal.
- **No forecasting.** The system interprets demand evidence — censored days,
  promotion windows — but never produces its own forecast.

## Scope

- **One SKU, one node per case.** No portfolio contention: the system cannot decide
  which product deserves scarce budget. Competing priorities escalate to a human.
- **Three action types.** No transfers between nodes, no PO cancellation, no split
  deliveries, no supplier negotiation.
- **One currency, integer minor units.** No FX, no tax, no landed-cost modelling.
- **No perishability, no batch or expiry tracking.**
- **No supplier minimum *spend*** — only minimum order quantity per order.
- **Storage capacity is a single volume number per node per day.** No racking types,
  temperature zones or dock scheduling.

## Validation

- **Validation is independent of the agent, not of the world model.** The
  execution-layer checks (quantity, date, cost) compare against facts the supplier
  reported and are genuinely independent. The business-layer check re-derives the
  projection with the *same engine* the plan used, so an error in that engine would
  make the plan and its validation wrong in the same direction. This is why the
  engine carries its own unit tests rather than being trusted because validation
  agrees with it. A stronger design would validate against observed receipts.
- **Cost tolerance is a flat $1.00.** No percentage band, no per-supplier terms.
- **The replan budget is 2.** A supplier that short-ships every order indefinitely
  escalates after two attempts rather than looping.

## Agent behaviour

- **Investigation paths remain model-dependent.** The runner does not prescribe an
  evidence sequence: after loading the case, the model chooses the next relevant
  source, explains the business question for that call, and may skip, repeat, or add
  checks. The committed recordings are samples and several inspect broad evidence;
  they should not be interpreted as a hard-coded workflow.
- **Results are one sample.** Model behaviour varies between runs. The committed
  recordings are the specific runs the report describes.
- **The tool budget is 12 calls and the replan budget is 2.** Both are demo values.
- **Prompt injection is handled by instruction and by architecture, not by a
  classifier.** Supplier text is passed to the model as data with an instruction to
  treat it as such; the real protection is that the server gate revalidates every
  action regardless of what any text said.

## Infrastructure

- **SQLite, single writer.** Queries use SQLAlchemy Core and writes use optimistic
  versions, but PostgreSQL is untested and would require its driver and integration
  coverage before claiming support.
- **Runs are synchronous.** A run holds the HTTP request open for its duration. There
  is no queue, no worker and no scheduled background processing.
- **No authentication.** Every caller is "the buyer". Approvals record an approver
  label, not an authenticated identity.
- **The supplier is a mock.** It models partial confirmation, late confirmation,
  rejection and lost responses, but not EDI, rate limits, auth, or real network
  behaviour.
- **`POST /api/demo/reset` wipes the database** with no authorisation check. Demo
  affordance, not a production endpoint.

## Known edge cases not implemented

Identified during design, deliberately out of scope:

| Case | Status |
|---|---|
| Portfolio budget contention across products | Escalates; no optimisation |
| Delivery calendars, working days, node timezones affecting ETA | Dates are plain, timezone recorded but unused |
| Supplier reliability scoring feeding candidate ranking | Column exists, unused in ranking |
| Out-of-order or duplicated supplier events | Table and dedup key exist; processing loop not built |
| Quote expiry *during* an open approval window | Revalidation catches it at execution; no proactive warning |
| Partial receipt of a confirmed order | Modelled in the schema, not exercised by any fixture |
| Multi-currency, tax, contractual penalties | Not modelled; would need to escalate as unsupported |

## What this is not

It is a demonstration of a decision-and-validation loop, not a replenishment system.
It does not attempt to be a forecasting engine, an optimiser, or a supplier
management platform.
