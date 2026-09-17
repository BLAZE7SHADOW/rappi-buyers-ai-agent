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

## No Supabase, but the dialect is portable

Hosted Supabase would mean either committing credentials (forbidden by the brief),
sharing one mutable database across reviewers — where the demo-reset endpoint would
wipe someone else's session — or requiring Docker. None of its strengths (auth,
storage, realtime) are needed here.

SQLAlchemy Core keeps the dialect portable, so `DATABASE_URL=postgresql://…` works
unchanged. The "SQLite is single-writer, would this scale?" question therefore has a
concrete answer rather than a hedge.

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
