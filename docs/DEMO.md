# Demo script

A 4–5 minute walkthrough of the headline case. The point to land is the **feedback
loop**: the agent acts, the system checks whether it actually worked, and disagreement
with reality reopens the case.

## Before recording

```bash
# Terminal 1 — reset to a clean state, then start the backend
cd backend && PYTHONPATH=..:. ../.venv/bin/python -m app.db.seed && cd ..
.venv/bin/python -m uvicorn app.main:app --app-dir backend --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev
```

Open `http://localhost:5173`. Confirm the supplier-behaviour selector on CASE-F1 reads
**`confirm_partial`** — that is what drives the reopen.

On the queue, briefly open **New case** to show that a buyer can submit an incoming
quantity and business reason. The form previews inventory, forecast, budget, storage,
supplier coverage and baseline exposure from system records; those constraints are
read-only. Close the form and continue with F1 for the deterministic walkthrough.

---

## 1 · The situation (30s)

Open **F1 — SKU-1001**.

> "The purchasing system recommends buying 800 units. The buyer's job is to decide
> whether that's right. It isn't."

Point at the three **Supply picture** calculations:

> "1,200 units on hand, but 150 are reserved and 50 are in quarantine — so 1,000 are
> actually usable. Demand is 100 a day over a 28-day horizon, so 2,800 total. And
> there's already a purchase order for 2,000 units."

> "Total supply is 3,000 against demand of 2,800. **There is no shortage of volume.**"

## 2 · The real problem (30s)

Point at the **Projection** chart:

> "The existing order lands on day 14. Stock runs out on day 10. That red band is
> four days and 400 units of demand we simply don't serve. This is a timing problem,
> and buying more units doesn't fix timing."

## 3 · Run the agent (60s)

Click **Run live agent**. If no API key is available, click **Replay recorded agent**;
the UI labels the run as replayed while still exercising the real application workflow.
While it runs:

> "The agent has nine tools. Six read evidence, one runs the simulation, two write to
> the case. There is deliberately no tool that places an order — it can propose, but
> it cannot execute. That's architectural, not a prompt instruction."

Point at **Path chosen for this case** as it updates:

> "This is not a predefined checklist. These are the calls the model actually chose
> for this case, in order. Each row records the business question it intended to
> answer and the result. It may skip, repeat or add checks, and a replan gets a new
> path. The raw payloads remain available only in the technical audit log."

When it finishes, open **Alternatives compared**:

> "It called the simulator, which scored every option. Look at the bottom two rows —
> the recommended 800 units, struck out. **$12,000 against a $10,000 budget.** The
> system doesn't just say 'infeasible', it says exactly which constraint bound and by
> how much."

> "And the winner: expedite the order that already exists, four days earlier, for
> **$450**. Zero unmet demand, at under 4% of the cost of buying more."

Show the **proposal**:

> "Disposition 'reject' — the recommendation. Action 'expedite' — what should actually
> happen. Those are separate on purpose. Rejecting a purchase is still a decision."

## 4 · Approval (30s)

> "The $450 fee is above the $250 autonomy limit, so the server requires a buyer. The
> agent didn't decide that and can't override it."

Click **Approve**.

If you also show a low-risk case (F2 or F3), the same gate reaches the opposite
conclusion and the plan executes without you. Point at the green **"Authorized
automatically under delegated authority"** panel before anyone reads it as the agent
doing as it pleased:

> "Nothing here was skipped. The same gate ran and granted authority, because the
> spend is inside the limit and no demand is left unserved — it says so, with the
> numbers. The gate decision is in the audit log, and the action is still validated
> independently afterwards. Autonomy is a policy outcome, not the absence of one." 

## 5 · The feedback loop — the important part (90s)

The page refreshes into the **Verdict** panel.

> "Here's what separates this from a chatbot that says 'done'. The supplier confirmed
> **1,200 of 2,000 units** and cancelled the rest."

Walk the three columns:

> "Expected 2,000. Actual 1,200. Delta minus 800."

Point at the checks:

> "Quantity check fails. Date check passes — it did arrive on time. Cost check passes.
> And the business check fails: 600 units of demand are still unserved from October 9."

> "Verdict: **PARTIAL**. Not success. And crucially, this is computed from the
> database and the authorised plan — it never reads what the agent claimed. If the
> agent had reported complete success, the verdict would still say PARTIAL."

Point at the state badge:

> "The case has reopened. Replan count is 1."

## 6 · Replan (45s)

Click **Run live agent** (or **Replay recorded agent**) again.

> "It's now looking at what actually happened, not what it hoped for. The expedite is
> spent. 600 units are still short."

Show the new comparison:

> "SUP-A can cover all 600. SUP-B is cheaper but leaves 100 units unserved. It picks
> the one that closes the gap."

Approve. The verdict comes back **PASS**, and the case resolves.

> "Two orders. No duplicates. And the second order only exists because the system
> checked its own work."

## 7 · Close (30s)

Either point at `backend/evals/report.md`:

> "Eight scenarios, scored on the assignment's own six evaluation questions. All
> eight pass against the live model, and the runs are recorded so they replay
> deterministically without an API key."

Or demonstrate recovery directly — set supplier behaviour to **`timeout_after_success`**
on another case and run it:

> "The supplier commits and the response is lost. The executor doesn't retry blindly —
> it asks the supplier what it recorded for that idempotency key, finds the commitment,
> and reconciles. One order, not two. That's the failure that creates duplicate
> purchase orders in real systems."

---

## 8 · Two short codas, if there is time (60s)

**F7 — the agent asks instead of guessing.** Sales flagged a possible 500-unit
corporate order that exists in no forecast, promotion or PO.

> "It can't verify this, and it changes the order by 500 units — the system plans
> the horizon both ways and compares. So it doesn't guess and it doesn't bury it in
> an assumption: it stops and asks, with both options costed and a default stated.
> Answer it, and it resumes and orders to the answer."

> "And this isn't the model deciding to be careful. The plan is tested against both
> worlds, and if they need materially different orders the gate stops the case
> whether or not the agent thought to ask. That mattered — before it worked this
> way, the model asked in about half of runs."

**F8 — the agent acts alone.** A small replenishment fully inside delegated authority.

> "No approval step here, and nothing was skipped. The same gate ran and granted
> authority because the spend is inside the limit and no demand is left unserved —
> the green panel says so with the numbers. It ordered, and the validator still
> checked the result independently. Autonomy is a policy outcome, not the absence
> of one."

---

## Fallback if the live agent misbehaves

Model runs vary. If a run goes sideways mid-demo, say so plainly, reset the demo, and
use the clearly labelled **Replay recorded agent** button. The CLI equivalent is:

```bash
cd backend && PYTHONPATH=..:. ../.venv/bin/python -m evals.run_evals --only F1
```

The replay exercises the real tools, gate, executor and validator — only the model's
turns come from disk.

## Questions worth pre-loading

- **"What if the agent hallucinates a number?"** Proposal terms are resolved from
  system records and checked by `simulate_plan`; unit price comes from the supplier
  quote and expedite quantity from the existing order. The gate re-simulates current
  state before execution, so model prose cannot authorise a conflicting action.
- **"Why not LangGraph or Temporal?"** Both evaluated and declined — see
  [DECISIONS.md](DECISIONS.md). The Temporal properties are implemented directly and
  mapped in [ARCHITECTURE.md](ARCHITECTURE.md#durable-execution).
- **"Would this scale?"** The workflow uses durable state, idempotency keys and
  optimistic versions. PostgreSQL and a workflow engine are the production path,
  but only SQLite is verified in this submission.
- **"What doesn't it do?"** [LIMITATIONS.md](LIMITATIONS.md) lists the modelling,
  agent and infrastructure boundaries plainly.
