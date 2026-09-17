# AI Purchasing Agent

An agent that reviews a purchasing situation, investigates it, decides what should
happen, executes within delegated authority, and then **checks whether what it did
actually worked**.

## The idea in one paragraph

> The agent **proposes**. A deterministic engine decides **feasibility**. A policy
> gate **authorises**. An idempotent executor **acts**. An independent validator
> checks **what actually happened** — and when reality disagrees with the plan, the
> case **reopens and the agent replans**.
>
> The LLM never does arithmetic, never approves itself, and never declares success.

Each of those is a structural property, not a prompt instruction. The agent has no
tool that can execute a purchase; proposal terms are grounded in authoritative
records and checked by `simulate_plan`; and the validator that judges an outcome
never sees what the agent claimed.

## The artifact that matters: the validation verdict

Every executed action produces one of these. It is computed from the authorised plan
and the persisted state — not from the agent's report:

```json
{
  "verdict": "PARTIAL",
  "expected": { "qty": 2000, "receipt_date": "2026-09-27", "cost_minor": 45000 },
  "actual":   { "qty": 1200, "receipt_date": "2026-09-27", "cost_minor": 45000,
                "cancelled_qty": 800,
                "supplier_note": "Only 1200 of 2000 units available. Remaining 800 cancelled, not backordered." },
  "deltas":   { "qty": -800, "cost_minor": 0, "receipt_days_late": 0 },
  "checks": [
    { "layer": "execution", "name": "supplier_and_sku_match",           "passed": true  },
    { "layer": "execution", "name": "qty_matches_authorized",           "passed": false },
    { "layer": "execution", "name": "date_matches_authorized",          "passed": true  },
    { "layer": "execution", "name": "cost_within_authorized_tolerance", "passed": true  },
    { "layer": "business",  "name": "coverage_gap_closed",              "passed": false }
  ],
  "residual_exposure": { "unmet_units": 600, "first_stockout_date": "2026-10-09" },
  "follow_up": "reopened_case"
}
```

A `PARTIAL` or `FAIL` verdict reopens the case and increments a replan counter. The
agent then replans **against what actually happened**, not against what it hoped for.

## The headline case

The brief says the recommendation *"should not necessarily be assumed to be
correct."* So the flagship fixture is one where it is wrong.

**Round 1 — the recommendation is rejected**

The system recommends buying **800 units** of SKU-1001. The agent finds:

| Fact | Value |
|---|---|
| Usable stock | 1,000 (1,200 on hand − 150 reserved − 50 quarantined) |
| Demand | 100/day for 28 days = 2,800 |
| Existing PO-501 | 2,000 units, confirmed, arriving day 14 |
| Projected shortage | **400 units**, starting 2026-09-27 |

Total supply (3,000) already exceeds total demand (2,800). **This is a timing
problem, not a volume problem.** The engine ranks every option:

```
OK     0 unmet  $   450.00  Expedite PO-501 by 4 days to 2026-09-27
OK     0 unmet  $ 7,000.00  Order 400 units from SUP-B, arriving 2026-09-20
OK     0 unmet  $ 7,500.00  Order 500 units from SUP-A, arriving 2026-09-24
OK   400 unmet  $     0.00  Keep the existing plan
XX     0 unmet  $12,000.00  Order 800 units from SUP-A  ← budget: exceeds $10,000 available
XX     0 unmet  $14,000.00  Order 800 units from SUP-B  ← budget: exceeds $10,000 available
```

The recommended 800 units is **infeasible on budget**. Expediting the order that
already exists closes the entire gap for **$450** — under 4% of the cost. The $450
fee exceeds the $250 expedite autonomy limit, so a buyer must approve it.

**Round 2 — the supplier cannot fulfil, and the case reopens**

The supplier confirms only **1,200 of 2,000** units and cancels the rest. Validation
returns **PARTIAL** with 600 units of residual exposure from 2026-10-09. The case
reopens and the agent replans:

```
OK     0 unmet  $ 9,000.00  Order 600 units from SUP-A, arriving 2026-09-24
OK   100 unmet  $ 8,750.00  Order 500 units from SUP-B, arriving 2026-09-20
OK   600 unmet  $     0.00  Keep the existing plan
XX     0 unmet  $12,000.00  Order 800 units from SUP-A  ← still over budget
```

*Now* a new purchase order is genuinely justified. SUP-A closes the gap; SUP-B is
cheaper but leaves 100 units unserved. The agent orders 600 from SUP-A, the buyer
approves, and validation returns **PASS**. Two orders, zero duplicates.

One narrative covers Scenario 1 (accept/modify/reject/investigate), Scenario 2
(supplier cannot fulfil), Scenario 4 (a constraint blocks the recommendation), and
the full feedback loop.

## Buyer workflow in the demo

The home page is an exception queue rather than a chatbot. It shows the incoming
signal, projected exposure, latest agent decision, workflow owner, validation status,
and replan count for every case. Open a row to see the adaptive investigation path
the agent actually chose, its reason and result for every step, the evidence,
28-day projection, feasible and infeasible plans, decision proof checklist, approval
gate, independent verdict, and technical audit log.

Buyers can also choose **New case** and submit a recommendation for an existing
product and fulfillment node. Before submission, the form previews the system's
usable inventory, forecast, budget headroom, storage headroom, supplier coverage,
and projected shortage. The buyer supplies the quantity and business reason; they
cannot edit operational constraints. This separation matters: the agent is reviewing
an incoming recommendation against source-system facts, not validating data the
requester chose to make the recommendation look feasible.

A buyer-created case can run against the live model. Recorded replay is intentionally
limited to the six fixed evaluation fixtures because those transcripts are tied to
known evidence and expected outcomes.

## Setup

Requires **Python 3.11+** and **Node 22.12+** (required by the frontend test and
build toolchain).

```bash
git clone https://github.com/BLAZE7SHADOW/rappi-buyers-ai-agent.git
cd rappi-buyers-ai-agent

python3.11 -m venv .venv
source .venv/bin/activate       # macOS / Linux; your prompt will show (.venv)
.venv/bin/pip install -r backend/requirements.txt

cp .env.example .env          # then add your GEMINI_API_KEY
```

The agent needs an LLM key for live runs. Gemini is the default; Anthropic works by
setting both `AI_PROVIDER` and an Anthropic `AI_MODEL`. Without a key, the browser
offers an explicitly labelled replay of the recorded model runs so a reviewer can
still exercise the real tools, gate, executor, validator, and F1 replan loop.

### Run

Seed once, then start the backend and frontend in separate terminals:

```bash
# 1. Seed the demo data
cd backend && PYTHONPATH=..:. ../.venv/bin/python -m app.db.seed && cd ..

# 2. Backend  → http://127.0.0.1:8000
.venv/bin/python -m uvicorn app.main:app --app-dir backend --port 8000 --host 127.0.0.1

# 3. Frontend → http://localhost:5173
cd frontend && npm ci && npm run dev
```

### Tests and evaluations

```bash
.venv/bin/python -m pytest backend/tests -q         # 69 domain, service, loop + API tests

cd frontend
npm test && npm run lint && npm run build            # component tests + static checks

cd backend
PYTHONPATH=..:. ../.venv/bin/python -m evals.run_evals                 # replay (no key needed)
PYTHONPATH=..:. ../.venv/bin/python -m evals.run_evals --live --record # call the real model
```

Evaluation output lands in `backend/evals/report.md`. The report scores each fixture
on the assignment's six evaluation questions; a question a fixture does not exercise
is marked `n/a` and excluded rather than counted as a pass.

F1 runs the agent **twice** — once to decide, and again after validation reopens the
case — so the feedback loop is exercised against the live model rather than described.
The evaluation asserts that the replan proposes something *different* from the action
that failed, and that the case actually reaches a conclusion.

## How the agent works

Nine tools. Six read evidence, one computes, two write to the case:

| Tool | Purpose |
|---|---|
| `get_case_context` | Trigger, policy, autonomy limits, prior proposals, known unknowns |
| `get_inventory` | On-hand broken into reserved / quarantined / damaged → usable |
| `get_demand_evidence` | Forecast, recent sales, stock availability, promotions |
| `get_open_orders` | Outstanding quantity, acknowledgement, overdue status |
| `get_supplier_options` | Quotes with price, MOQ, pack size, lead time, expiry, expedite terms |
| `get_constraints` | Budget headroom, storage headroom, autonomy limits |
| `simulate_plan` | **The only source of numbers** — projection before/after, feasibility |
| `propose_plan` | Records the decision; the server gates it and executes autonomous plans |
| `ask_buyer` | Asks for context or a judgement call, and pauses |

A buyer is consulted when the answer would change the order — and that is decided by
the engine, not by the model. An unconfirmed input is costed both ways; if the two
worlds need materially different orders the gate stops the case and puts the question
to the buyer with both quantities shown. Otherwise the agent decides and records its
assumption. The line is easy to get wrong in both directions — an agent that never
asks quietly guesses, and one that always asks is a form that takes longer than doing
the job — which is exactly why it is not left to a prompt. See
[docs/DECISIONS.md](docs/DECISIONS.md) for what happened when it was.

**There is deliberately no `execute` tool.** Execution happens server-side immediately
when the gate grants delegated authority, or after a buyer approves. That is why the
agent cannot approve its own spending — it is a property of the architecture, not a
promise about prompting.

The loop is bounded: 12 tool calls, 2 replans per case. Repeated identical calls are
refused with an explanation instead of looping. Running out of budget produces a
*pending investigation with findings*, never a fabricated recommendation.

After the case context is loaded, there is no fixed evidence checklist. The model
chooses the next tool from the trigger and the previous result, supplies a short
buyer-facing reason for that choice, and may skip, repeat, or add checks. That reason
is enforced at the tool layer, not merely scored afterwards: an evidence or simulation
call without one is refused and returns no data. The case page renders this actual
path as it happens; it does not display planned steps that the agent never chose.

## How decisions are made

Hard constraints first — budget, capacity, MOQ and pack size, supplier eligibility,
quote validity. Among feasible plans the ordering is explicit and stated in code:

1. meet the service target (fewest unmet units),
2. avoid excess exposure (least surplus stock),
3. minimise incremental cost.

No hidden weighted score. Infeasible options are **kept, not discarded**, because
explaining why the obvious choice was unavailable is most of the value.

Three levers exist and no more: `keep_plan`, `create_po`, `expedite_po`. Keeping the
action set this small means every action the agent can take is one a human can audit.

## Validation, in three layers

1. **Proposal validity** — sufficient evidence, hard constraints pass. Checked before
   execution, and re-checked immediately before committing, because a plan approved
   ten minutes ago may no longer be affordable.
2. **Execution validity** — does the persisted order match what was authorised:
   supplier, product, node, quantity, date, charged cost?
3. **Business outcome validity** — does the confirmed supply actually close the gap
   the plan existed to close?

A pending acknowledgement is reported as *awaiting confirmation*, never as coverage.
Supplier confirmation and physical receipt are different milestones.

## Requirements traceability

| Requirement from the brief | Where it is satisfied |
|---|---|
| Full-stack | React + Vite workbench, FastAPI + SQLite backend |
| Investigate → decide → act | `app/agent/loop.py` → `services/gate.py` → `services/executor.py` |
| Recommendation not assumed correct | **F1** rejects the 800; **F3** modifies it down |
| Multiple interacting constraints | F1 (budget) · F3 (capacity **and** excess stock) · F6 (budget exhausted) |
| **S1** accept / modify / reject / investigate | F2 · F3 · F1 · **F7** |
| **S2** supplier cannot fulfil | F1 round 2: partial confirmation → residual exposure |
| S2 — source elsewhere / another supplier | Replan compares SUP-A vs SUP-B |
| S2 — additional PO required | F1 replan creates the 600-unit follow-up |
| S2 — existing inventory sufficient | `keep_plan` is always a scored candidate |
| S2 — escalate | F6, and bounded-retry exhaustion |
| **S3** demand / forecast changed | F4: promotion-bounded uplift + stockout-censored sales |
| **S4** constraint blocks the purchase | F1 (budget blocks the 800) · F6 (nothing feasible) |
| What information the agent needs | Tools 1–6 |
| What tools / APIs | 9 tools + mock supplier API |
| What data should exist | 18 tables, 6 fixtures |
| How decisions are made | `domain/candidates.py::rank` |
| What actions are allowed | Exactly three plan types |
| When human approval applies | `services/gate.py`; approval bound to proposal version. **F8** shows the opposite case: inside delegated authority, the gate authorises and the server executes with no human |
| How results are validated | `services/validator.py`, three layers |
| **Feedback loop** | `PARTIAL`/`FAIL` → reopen → replan → revalidate |
| Outcome differs from expected | F1 partial confirmation; F5 timeout-after-success |
| Evaluation approach | `backend/evals/`, scored on the brief's six questions |
| Architecture diagram | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Mock APIs / datasets | `app/integrations/mock_supplier.py`, `fixtures/` |

## Test fixtures

| ID | Situation | Correct outcome |
|---|---|---|
| **F1** | 800 recommended; supply exists but lands too late | Reject → expedite → PARTIAL → reopen → 600-unit order → PASS |
| **F2** | 800 recommended, genuinely needed and affordable | Accept; one PO |
| **F3** | 800 recommended, capacity and excess limits bind | Modify down to 500 |
| **F4** | Sales running 2.6× forecast, promotion ends in 6 days | Bound the uplift; do not extrapolate |
| **F5** | Supplier commits, response lost in transit | Recover by idempotency key; exactly one order |
| **F6** | Real shortfall, zero budget | Escalate; no fabricated solution |
| **F7** | Unconfirmed bulk order that no system of record holds | Cost it both ways; stop for the buyer; order to the answer |
| **F8** | Small, cheap, fully covered replenishment | Execute and validate autonomously; no human |

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — components, data model, durable-execution design
- [docs/DECISIONS.md](docs/DECISIONS.md) — what was deliberately cut, and why
- [docs/POLICY.md](docs/POLICY.md) — planning rules, constraints, authority and validation
- [docs/DEMO.md](docs/DEMO.md) — repeatable reviewer walkthrough
- [docs/LIMITATIONS.md](docs/LIMITATIONS.md) — what this does not model
- [backend/evals/report.md](backend/evals/report.md) — observed results against the brief’s six questions

## Submission checklist

| Required artifact | Included at |
|---|---|
| Complete source code | `backend/`, `frontend/`, `fixtures/` |
| Setup and run instructions | [Setup](#setup), including supported runtimes and no-key replay |
| Architecture diagram | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#components) |
| Description of the approach | [The idea](#the-idea-in-one-paragraph), [How the agent works](#how-the-agent-works), [docs/DECISIONS.md](docs/DECISIONS.md) |
| Test scenarios and evaluation | [Test fixtures](#test-fixtures), `backend/evals/`, [evaluation report](backend/evals/report.md) |
| Mock APIs and datasets | `backend/app/integrations/mock_supplier.py`, `fixtures/`, recorded runs in `backend/evals/recordings/` |
| Decision validation explanation | [Validation](#validation-in-three-layers), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), `backend/app/services/validator.py` |
| Working demo | Local application at `http://localhost:5173`; walkthrough in [docs/DEMO.md](docs/DEMO.md) |
| Environment template | [.env.example](.env.example) with provider, database, autonomy and loop settings |
| Secret hygiene | `.env`, database files, virtual environments and build outputs are ignored by `.gitignore` |

## Modelling assumptions

Stated here because they change how the numbers should be read:

- **Daily resolution.** Intraday stockouts are outside the model.
- **Receipts arrive before that day's demand.** A delivery landing on the day stock
  would run out prevents the stockout.
- **Unmet demand is lost, not backlogged.** It is recorded separately and physical
  inventory is clamped at zero.
- **Only confirmed supply enters the baseline.** Overdue or unacknowledged orders are
  surfaced as uncertainty rather than silently counted.
- **One currency, integer minor units.** No FX, no tax.
