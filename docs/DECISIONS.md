# Decisions

What was deliberately left out, and why. Scope judgement on an ambiguous problem is
part of the work, so these are recorded rather than quietly omitted.

## No agent framework (LangGraph, AutoGen, CrewAI)

Evaluated and declined. Their value is multi-agent orchestration; this is a
single-agent tool-calling problem where the hard parts — the deterministic engine,
the policy gate, the validator — are things no framework provides.

A direct loop is about 200 lines. It keeps the gate structurally un-bypassable,
makes every tool call auditable in `case_events`, and leaves nothing in the system
that cannot be explained line by line. A framework would have added a dependency
between the author and questions like "why did the agent retry there?"

## No Temporal, but its properties are implemented

This genuinely is a durable-execution problem, and Temporal is the right production
answer. It is the wrong take-home answer: it needs a server, and it forces a reviewer
to run infrastructure before seeing the demo.

The five properties it would provide are implemented directly over SQLite and mapped
explicitly in [ARCHITECTURE.md](ARCHITECTURE.md#durable-execution).

## No Supabase

Hosted Supabase would mean either committing credentials (forbidden by the brief),
sharing one mutable database across reviewers — where the demo-reset endpoint would
wipe someone else's session — or requiring Docker. None of its strengths (auth,
storage, realtime) are needed here.

SQLAlchemy Core keeps the queries portable, but only SQLite is verified in this
submission. A production move to PostgreSQL would add its driver plus concurrency and
migration tests rather than relying on an untested URL swap.

## No separate non-LLM demo runner

An obvious way to make the system runnable without an API key is to write a
deterministic agent that follows the same tool sequence. That means writing the agent
twice, and the two implementations drift.

Record-and-replay achieves the same thing at a fraction of the cost: a live run is
recorded once, and replaying it exercises the *real* tools, gate, executor and
validator — only the model's turns come from disk. A replay that runs past its
recording raises rather than inventing a turn.

## Three action types, not more

`keep_plan`, `create_po`, `expedite_po`. Stock transfers between nodes, PO
cancellation, split deliveries and supplier renegotiation were all considered and
left out.

Keeping the action set this small means every action the agent can take is one a
human can audit, and each has a real executor, a real validator and real failure
handling. Five half-wired actions would demonstrate less than three complete ones.
The agent may *name* an unsupported intervention as needed external coordination; it
must never claim to have executed one.

## Nine tools, not twelve

An earlier design had twelve. `submit_plan` was removed entirely — execution is
server-triggered after authorisation, which is what makes "the agent cannot approve
itself" architectural rather than a prompt instruction. Others were merged where the
split bought nothing.

## One SKU and one node per case

The schema supports multiple products and nodes, and the seed data uses several. But
a *case* is scoped to one SKU at one node.

Multi-product optimisation raises portfolio contention — which product deserves
scarce budget — and that is a genuine business judgement, not an arithmetic problem.
Pretending to solve it with a weighted score would be worse than declining to.

## Edge cases documented rather than implemented

An earlier design enumerated 29. About ten are implemented and tested; the rest are
recorded in [LIMITATIONS.md](LIMITATIONS.md). A register of edge cases that are
listed but not handled is a liability, not an asset.

## Assertions on outcomes, not traces

Evaluations assert dispositions, quantity bands, constraint compliance, action counts
and verdicts. They never assert exact wording or a fixed tool order.

An evaluation that demands one exact trace measures conformity rather than judgement,
and would fail a run that reached the right answer by a better route. Where several
plans are defensible, the fixture specifies an acceptable band.

## A decision brief plus an adaptive activity path

The case page leads with the exception, business impact, recommended change, approval
owner and constraints. It also translates the actual investigation calls into
quick-commerce language, including why the agent selected each call and what it
found. This path is generated from persisted events rather than a fixed UI checklist.
Detailed source records, simulated alternatives and raw payloads remain available
through progressive disclosure; buyers do not have to interpret tool names or JSON.

This follows the workflow pattern used by established procurement systems: Microsoft
Dynamics presents planning changes as action messages that a planner may apply;
SAP Guided Buying simulates and validates a requisition before approval; and Oracle
routes approval tasks when human intervention is required. The implementation keeps
the useful pattern without copying any vendor interface:

- [Dynamics 365 action messages](https://learn.microsoft.com/en-us/dynamics365/supply-chain/master-planning/action-messages)
- [SAP Guided Buying request flow](https://help.sap.com/doc/22983cba504a482eb7af2b59419e0eee/2508/en-US/GuidedBuyingAdministrationGuide.pdf)
- [Oracle procurement approval tasks](https://docs.oracle.com/en/cloud/saas/procurement/25c/oapro/approval-task.html)

Human approval is risk-based rather than universal. Hard constraints cannot be
waived through an approval button. Feasible actions require a buyer when spend or
fees exceed delegated authority, evidence is missing, or demand remains unserved.
Low-risk feasible actions execute automatically and are still independently validated.
