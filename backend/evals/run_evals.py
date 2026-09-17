"""Agent evaluation harness.

The six checks below are the assignment's own evaluation questions, used verbatim
as the report's columns:

1. Was the decision correct?
2. Did the agent obtain the necessary information?
3. Did it respect relevant constraints?
4. Did it take the appropriate action?
5. Did it validate the result?
6. What happens when the initial action does not work?

Assertions target outcomes and invariants, never exact prose or a fixed tool
order. Several fixtures admit more than one defensible plan, so those are scored
against an acceptable band rather than a single number -- an evaluation that
demands one exact trace measures conformity, not judgement.

Usage:
    python -m evals.run_evals                  # replay recordings (deterministic, no key)
    python -m evals.run_evals --live           # call the real model
    python -m evals.run_evals --live --record  # call the model and save recordings
    python -m evals.run_evals --only F1 F4
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.agent.loop import run_case  # noqa: E402
from app.agent.providers import NoProviderKey, get_provider  # noqa: E402
from app.db import schema as s  # noqa: E402
from app.db.engine import reset_database, transaction  # noqa: E402
from app.db.repo import load_case, load_events  # noqa: E402
from app.db.seed import seed_fixture  # noqa: E402
from app.services.proposals import approve  # noqa: E402
from evals.replay import (  # noqa: E402
    RecordingProvider, ReplayProvider, has_recording, recording_path,
)
from fixtures import FIXTURES  # noqa: E402

REPORT = Path(__file__).resolve().parent / "report.md"
RESULTS = Path(__file__).resolve().parent / "results.json"

# Evidence each fixture cannot be decided responsibly without.
REQUIRED_EVIDENCE = {
    "F1": ["get_open_orders", "simulate_plan"],
    "F2": ["simulate_plan"],
    "F3": ["get_constraints", "simulate_plan"],
    "F4": ["get_demand_evidence"],
    "F5": ["get_open_orders", "simulate_plan"],
    "F6": ["get_constraints", "simulate_plan"],
}


@dataclass
class Check:
    question: str
    passed: bool
    detail: str
    # A question the fixture never exercises is not a pass. Scoring it as one
    # inflates the result; it is reported as N/A and excluded from the total.
    applicable: bool = True


@dataclass
class Result:
    fixture_id: str
    case_id: str
    mode: str
    provider: str = ""
    model: str = ""
    outcome: str = ""
    tool_calls: int = 0
    replanned: bool = False
    checks: list[Check] = field(default_factory=list)
    error: str = ""

    @property
    def passed(self) -> bool:
        return not self.error and all(c.passed for c in self.checks if c.applicable)

    def to_dict(self) -> dict:
        return {
            "fixture_id": self.fixture_id, "case_id": self.case_id, "mode": self.mode,
            "provider": self.provider, "model": self.model, "outcome": self.outcome,
            "tool_calls": self.tool_calls, "replanned": self.replanned,
            "passed": self.passed, "error": self.error,
            "checks": [{"question": c.question, "passed": c.passed,
                        "applicable": c.applicable, "detail": c.detail}
                       for c in self.checks],
        }


# --------------------------------------------------------------------------- #
# Inspection helpers
# --------------------------------------------------------------------------- #


def _set_supplier_behavior(case_id: str, behavior: str) -> None:
    with transaction() as conn:
        conn.execute(s.cases.update().where(s.cases.c.case_id == case_id)
                     .values(supplier_behavior=behavior))


def _case_state(case_id: str) -> str:
    with transaction() as conn:
        return load_case(conn, case_id)["state"]


def _state(case_id: str) -> dict:
    with transaction() as conn:
        case = load_case(conn, case_id)
        proposals = conn.execute(
            select(s.proposals).where(s.proposals.c.case_id == case_id)
            .order_by(s.proposals.c.version)
        ).mappings().all()
        actions = conn.execute(
            select(s.actions).where(s.actions.c.case_id == case_id)
        ).mappings().all()
        orders = conn.execute(
            select(s.purchase_orders).where(s.purchase_orders.c.sku == case["sku"])
        ).mappings().all()
        supplier_records = conn.execute(select(s.supplier_ledger)).mappings().all()
        events = load_events(conn, case_id)
    return {
        "case": case,
        "proposals": [dict(p) for p in proposals],
        "actions": [dict(a) for a in actions],
        "orders": [dict(o) for o in orders],
        "supplier_records": [dict(r) for r in supplier_records],
        "events": events,
        "tools_used": [e["payload"].get("tool") for e in events if e["kind"] == "tool_call"],
    }


# --------------------------------------------------------------------------- #
# The six questions
# --------------------------------------------------------------------------- #


def q1_decision_correct(fixture_id: str, expected: dict, st: dict) -> Check:
    q = "Was the decision correct?"
    if not st["proposals"]:
        return Check(q, False, "No proposal was recorded.")
    # The fixture's expectation describes the decision on the incoming
    # recommendation, so it is judged against the FIRST proposal. A later
    # proposal from a replan is a different decision about a changed world, and
    # is judged by Q6 instead.
    p = st["proposals"][0]
    want = expected.get("disposition")

    if fixture_id == "F4":
        # Demand-spike fixture: the decision is judged on whether the quantity
        # reflects promotion-bounded demand rather than naive extrapolation.
        args = json.loads(p["action_args_json"])
        qty = int(args.get("qty") or 0)
        naive_need = expected["naive_sustained_total_demand"]
        ok = qty < naive_need * 0.75
        return Check(q, ok,
                     f"Proposed {qty} units; naive extrapolation would imply roughly "
                     f"{naive_need} units of demand. "
                     + ("Bounded the uplift." if ok else "Looks like naive extrapolation."))

    if want and p["disposition"] != want:
        return Check(q, False, f"Expected disposition '{want}', got '{p['disposition']}'.")

    band = expected.get("qty_band")
    if band:
        qty = int(json.loads(p["action_args_json"]).get("qty") or 0)
        if not (band[0] <= qty <= band[1]):
            return Check(q, False, f"Quantity {qty} outside the acceptable band {band}.")
        return Check(q, True, f"Disposition '{p['disposition']}', quantity {qty} within {band}.")

    if expected.get("qty"):
        qty = int(json.loads(p["action_args_json"]).get("qty") or 0)
        if qty != expected["qty"]:
            return Check(q, False, f"Expected {expected['qty']} units, proposed {qty}.")

    return Check(q, True, f"Disposition '{p['disposition']}' matches expectation.")


def q2_obtained_information(fixture_id: str, expected: dict, st: dict) -> Check:
    q = "Did the agent obtain the necessary information?"
    required = REQUIRED_EVIDENCE.get(fixture_id, [])
    used = set(st["tools_used"])
    missing = [t for t in required if t not in used]
    if missing:
        return Check(q, False, f"Never called: {', '.join(missing)}. Used: {sorted(used)}.")
    reasoned_tools = {
        "get_inventory", "get_demand_evidence", "get_open_orders",
        "get_supplier_options", "get_constraints", "simulate_plan",
    }
    unexplained = [
        e["payload"].get("tool") for e in st["events"]
        if e["kind"] == "tool_call"
        and e["payload"].get("tool") in reasoned_tools
        and not str(e["payload"].get("args", {}).get("reason", "")).strip()
    ]
    if unexplained:
        return Check(
            q, False,
            "Evidence was retrieved without a buyer-facing reason: "
            + ", ".join(unexplained),
        )
    return Check(
        q, True,
        f"Consulted {len(used)} distinct tools including {', '.join(required)}; "
        "every selected evidence and simulation call recorded why it was needed.",
    )


def q3_respected_constraints(fixture_id: str, expected: dict, st: dict) -> Check:
    q = "Did it respect relevant constraints?"
    for p in st["proposals"]:
        sim = json.loads(p["simulation_json"] or "{}")
        if p["state"] in ("approved", "executed") and sim and not sim.get("feasible", True):
            return Check(q, False,
                         f"Proposal {p['proposal_id']} was executed while infeasible: "
                         f"{sim.get('binding_constraints')}.")
    # Nothing may execute that breaches a hard constraint, regardless of approval.
    for a in st["actions"]:
        if a["state"] == "completed":
            v = json.loads(a["verdict_json"] or "{}")
            for c in v.get("checks", []):
                if c["name"] == "cost_within_authorized_tolerance" and not c["passed"]:
                    return Check(q, False, f"Action {a['action_id']} exceeded authorised cost.")
    return Check(q, True, "No executed action breached budget, capacity, MOQ or quote validity.")


def q4_appropriate_action(fixture_id: str, expected: dict, st: dict) -> Check:
    q = "Did it take the appropriate action?"
    if not st["proposals"]:
        return Check(q, False, "No proposal, so no action.")
    p = st["proposals"][0]          # the action for the original decision
    want = expected.get("action_type")
    if want and p["action_type"] != want:
        return Check(q, False, f"Expected action '{want}', got '{p['action_type']}'.")

    # Action count catches duplicates, which a type check alone would miss.
    completed = [a for a in st["actions"] if a["state"] == "completed"]
    # Only assert inaction when the fixture explicitly expects it. A fixture that
    # simply does not pin an action type (F4 judges quantity, not action) must not
    # be read as expecting nothing to happen.
    if want in ("none", "keep_plan") and completed:
        return Check(q, False, f"Expected no purchasing action, but {len(completed)} ran.")
    if want not in (None, "none", "keep_plan"):
        matching = [a for a in completed if a["action_type"] == want]
        if not matching:
            return Check(q, False, f"Expected a completed '{want}' action; none completed.")
    # One execution per proposal. More than that means a duplicate, which is the
    # failure this count exists to catch.
    if len(completed) > len(st["proposals"]):
        return Check(q, False,
                     f"{len(completed)} actions executed across {len(st['proposals'])} "
                     f"proposal(s) -- an action ran more than once.")
    return Check(q, True,
                 f"Action '{p['action_type']}'; {len(completed)} execution(s) across "
                 f"{len(st['proposals'])} proposal(s), no duplicates.")


def q5_validated_result(fixture_id: str, expected: dict, st: dict) -> Check:
    q = "Did it validate the result?"
    completed = [a for a in st["actions"] if a["state"] == "completed"]
    if not completed:
        # Nothing executed, so there is nothing to validate. That is correct for
        # reject/escalate outcomes, not a gap.
        if expected.get("action_type") in ("none", "keep_plan", None):
            expected_state = "escalated" if expected.get("action_type") == "none" else "resolved"
            if expected.get("action_type") and st["case"]["state"] != expected_state:
                return Check(
                    q, False,
                    f"No action was required, but the case stopped in '{st['case']['state']}' "
                    f"instead of '{expected_state}'.",
                )
            return Check(q, True, "No action executed and the case reached its terminal state.")
        return Check(q, False, "An action was expected but none executed.")
    unvalidated = [a for a in completed if not a["verdict_json"]]
    if unvalidated:
        return Check(q, False, f"{len(unvalidated)} executed action(s) have no verdict.")
    verdicts = [json.loads(a["verdict_json"])["verdict"] for a in completed]
    return Check(q, True, f"Every executed action carries a verdict: {', '.join(verdicts)}.")


def q6_handles_failure(fixture_id: str, expected: dict, st: dict) -> Check:
    q = "What happens when the initial action does not work?"
    case = st["case"]

    if fixture_id == "F5":
        # Lost response after a successful commit: one supplier commitment, one
        # local action, one order, and visible reconciliation evidence.
        count = len(st["orders"])
        want = expected.get("expected_po_count_after_retry", 1)
        recovered = any(e["label"] == "Recovered lost response via idempotency key"
                        for e in st["events"])
        ok = (count == want and len(st["supplier_records"]) == 1
              and len(st["actions"]) == 1 and recovered)
        return Check(q, ok,
                     ("After timeout recovery, one supplier record, one action, and "
                      f"{count} purchase order exist; reconciliation is in the audit trail.")
                     if ok else
                     (f"Recovery evidence incomplete: orders={count}, "
                      f"supplier_records={len(st['supplier_records'])}, "
                      f"actions={len(st['actions'])}, audit_event={recovered}."))

    partials = [json.loads(a["verdict_json"])["verdict"] for a in st["actions"]
                if a["verdict_json"]]
    if any(v in ("PARTIAL", "FAIL") for v in partials):
        if case["replan_count"] == 0 and case["state"] not in ("reopened", "escalated"):
            return Check(q, False, f"Verdict {partials} but the case did not reopen.")

        # Reopening is only half the loop. The half that matters is whether the
        # agent then investigated the new reality and proposed something else.
        if len(st["proposals"]) < 2:
            return Check(q, False,
                         f"Case reopened after {partials} but the agent produced no "
                         f"second proposal, so it never actually replanned.")

        first, last = st["proposals"][0], st["proposals"][-1]
        changed = (first["action_type"] != last["action_type"]
                   or first["action_args_json"] != last["action_args_json"])
        if not changed:
            return Check(q, False,
                         "The replan repeated the original action unchanged, which "
                         "would repeat the failure.")

        if case["state"] not in ("resolved", "escalated"):
            return Check(q, False,
                         f"The replan stopped in non-terminal state '{case['state']}'.")

        return Check(q, True,
                     f"Verdict {partials} reopened the case; the agent replanned from "
                     f"'{first['action_type']}' to '{last['action_type']}' and the case "
                     f"reached '{case['state']}' (replans: {case['replan_count']}).")

    if case["state"] == "escalated":
        return Check(q, True, "No feasible option existed; escalated rather than acting.")

    # Nothing went wrong here, so this fixture does not answer the question.
    # Marking it PASS would claim evidence this run does not contain.
    return Check(q, True,
                 f"Not exercised: the action succeeded and the case resolved "
                 f"('{case['state']}'). Failure handling is covered by F1 and F5.",
                 applicable=False)


CHECKS = [q1_decision_correct, q2_obtained_information, q3_respected_constraints,
          q4_appropriate_action, q5_validated_result, q6_handles_failure]


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


def run_fixture(fixture_id: str, *, live: bool, record: bool) -> Result:
    fixture = FIXTURES[fixture_id]
    reset_database()
    case_id = seed_fixture(fixture_id)

    mode = "live" if live else "replay"
    result = Result(fixture_id=fixture_id, case_id=case_id, mode=mode)

    try:
        if live:
            provider = get_provider()
            if record:
                provider = RecordingProvider(provider, recording_path(fixture_id))
        else:
            if not has_recording(fixture_id):
                result.error = ("No recording. Run with --live --record first, or use "
                                "--live to call the model directly.")
                return result
            provider = ReplayProvider(recording_path(fixture_id))

        run = run_case(case_id, provider=provider)
        result.provider, result.model = run["provider"], run["model"]
        result.outcome, result.tool_calls = run["outcome"], run["tool_calls"]

        # Approve anything the gate held back, so the evaluation exercises the
        # full path through execution and validation rather than stopping at the
        # approval boundary.
        _auto_approve(case_id)

        # If validation reopened the case, run the agent again. Reopening is only
        # half the feedback loop; the half that matters is the agent investigating
        # the new reality and proposing something different. The same provider is
        # reused so the recording captures both runs and replays them in order.
        if _case_state(case_id) == "reopened":
            result.replanned = True
            # The follow-up is a new order, so the supplier is allowed to fulfil it
            # normally. Leaving it short-shipping every order forever would test the
            # replan cap rather than the replan, and that cap is already enforced by
            # max_replans -> escalate.
            _set_supplier_behavior(case_id, "confirm_full")
            rerun = run_case(case_id, provider=provider)
            result.tool_calls += rerun["tool_calls"]
            result.outcome = f"{result.outcome} → replanned ({rerun['outcome']})"
            _auto_approve(case_id)

        if record and live and isinstance(provider, RecordingProvider):
            provider.save()

    except NoProviderKey as exc:
        result.error = str(exc)
        return result
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    st = _state(case_id)
    result.checks = [check(fixture_id, fixture.expected, st) for check in CHECKS]
    return result


def _auto_approve(case_id: str) -> None:
    """Stand in for the buyer so evaluations reach the validation stage."""
    with transaction() as conn:
        pending = conn.execute(
            select(s.proposals).where(s.proposals.c.case_id == case_id,
                                      s.proposals.c.state == "proposed")
        ).mappings().all()
        ids = [(p["proposal_id"], bool(p["approval_required"]),
                p["action_type"]) for p in pending]

    for proposal_id, needs_approval, action_type in ids:
        if action_type in ("none", "keep_plan"):
            continue
        if needs_approval:
            approve(case_id, proposal_id, approver="eval-harness")
        else:
            from app.services.proposals import authorize_and_execute
            authorize_and_execute(case_id, proposal_id)


def render_report(results: list[Result], started: datetime) -> str:
    questions = [c.question for c in results[0].checks] if results and results[0].checks else []
    lines = [
        "# Agent Evaluation Report",
        "",
        f"Generated: {started.isoformat(timespec='seconds')}",
        "",
        "Columns are the assignment's own evaluation questions. Assertions target "
        "outcomes and invariants, never exact wording or a fixed tool order; fixtures "
        "with more than one defensible plan are scored against an acceptable band.",
        "",
        "## Summary",
        "",
        "| Fixture | Mode | Model | Outcome | Tool calls | Replanned | Result |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        verdict = "PASS" if r.passed else "FAIL"
        lines.append(
            f"| {r.fixture_id} | {r.mode} | {r.model or '-'} | {r.outcome or r.error[:40]} "
            f"| {r.tool_calls} | {'yes' if r.replanned else '—'} | **{verdict}** |"
        )

    if questions:
        lines += ["", "## Per-question results", "",
                  "| Fixture | " + " | ".join(f"Q{i+1}" for i in range(len(questions))) + " |",
                  "|---" * (len(questions) + 1) + "|"]
        for r in results:
            cells = [("n/a" if not c.applicable else "PASS" if c.passed else "FAIL")
                     for c in r.checks] or ["-"] * len(questions)
            lines.append(f"| {r.fixture_id} | " + " | ".join(cells) + " |")
        lines += ["", "`n/a` means the fixture does not exercise that question. It is "
                  "excluded from the result rather than counted as a pass.", "",
                  "Legend:", ""]
        for i, q in enumerate(questions):
            lines.append(f"- **Q{i+1}** — {q}")

    lines += [
        "", "## Observations", "",
        "**Investigation is adaptive and auditable.** After the required case-context "
        "entry point, the runner does not prescribe a sequence. The model selects each "
        "source from the trigger and prior results, and Q2 fails if an evidence or "
        "simulation call does not record the buyer-facing business question it was "
        "chosen to answer. Broad evidence gathering is allowed when the decision needs "
        "it; it is an observed model choice rather than a fixed workflow.",
        "",
        "**Paths and decisions may differ without breaking the evaluation.** Assertions "
        "target necessary evidence and business outcomes rather than an exact trace, so "
        "a shorter or reordered investigation passes when it remains sufficient.",
        "",
        "**The feedback loop was recorded from a live model and is replayed through the real "
        "workflow.** F1 runs the recorded agent turns, executes, validates, and -- because "
        "the supplier short-ships -- runs the second recorded agent pass against the changed "
        "state. Q6 asserts that the second "
        "proposal differs from the first and that the case actually concludes; a replan "
        "that repeated the failed action, or left the case stuck in `reopened`, fails.",
        "",
        "**Validation is independent of the agent, not of the world model.** The "
        "execution-layer checks compare against supplier-reported facts and are fully "
        "independent. The business-layer check re-derives the projection using the same "
        "engine the plan used, so an error in that engine would affect plan and "
        "validation together. The engine is covered separately by unit tests for that "
        "reason.",
        "",
        "**Typed tool errors are recovered from.** In F6 the first `propose_plan` call "
        "omitted `disposition`; the tool returned `MISSING_FIELD` and the agent corrected "
        "the call on its next turn rather than failing the run.",
        "",
        "**Recorded runs are one sample.** Model behaviour varies between runs. The "
        "recordings in `recordings/` are the specific runs these results describe; "
        "re-recording with `--live --record` may take a different path.",
        "", "## Detail", ""]
    for r in results:
        lines.append(f"### {r.fixture_id} — {FIXTURES[r.fixture_id].case.get('title', '')}")
        lines.append("")
        if r.error:
            lines += [f"Run error: `{r.error}`", ""]
            continue
        lines += [f"Case `{r.case_id}` · mode `{r.mode}` · model `{r.model}` · "
                  f"outcome `{r.outcome}` · {r.tool_calls} tool calls", ""]
        for c in r.checks:
            mark = "n/a " if not c.applicable else "PASS" if c.passed else "FAIL"
            lines.append(f"- {mark} — **{c.question}** {c.detail}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run agent evaluations.")
    parser.add_argument("--live", action="store_true", help="Call the real model.")
    parser.add_argument("--record", action="store_true", help="Save turns for replay.")
    parser.add_argument("--only", nargs="*", help="Fixture ids, e.g. F1 F4.")
    args = parser.parse_args()

    ids = args.only or list(FIXTURES.keys())
    started = datetime.utcnow()
    results = [run_fixture(f, live=args.live, record=args.record) for f in ids]

    REPORT.write_text(render_report(results, started))
    RESULTS.write_text(json.dumps(
        {"generated": started.isoformat(), "live": args.live,
         "results": [r.to_dict() for r in results]}, indent=2))

    passed = sum(1 for r in results if r.passed)
    print(f"\n{passed}/{len(results)} fixtures passed.  Report: {REPORT}")
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        detail = r.error or f"{r.outcome}, {r.tool_calls} tool calls"
        print(f"  {mark}  {r.fixture_id}: {detail}")
        if not r.passed and not r.error:
            for c in r.checks:
                if not c.passed:
                    print(f"          - {c.question} {c.detail}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
