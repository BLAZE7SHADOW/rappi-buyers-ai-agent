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


@dataclass
class Result:
    fixture_id: str
    case_id: str
    mode: str
    provider: str = ""
    model: str = ""
    outcome: str = ""
    tool_calls: int = 0
    checks: list[Check] = field(default_factory=list)
    error: str = ""

    @property
    def passed(self) -> bool:
        return not self.error and all(c.passed for c in self.checks)

    def to_dict(self) -> dict:
        return {
            "fixture_id": self.fixture_id, "case_id": self.case_id, "mode": self.mode,
            "provider": self.provider, "model": self.model, "outcome": self.outcome,
            "tool_calls": self.tool_calls, "passed": self.passed, "error": self.error,
            "checks": [{"question": c.question, "passed": c.passed, "detail": c.detail}
                       for c in self.checks],
        }


# --------------------------------------------------------------------------- #
# Inspection helpers
# --------------------------------------------------------------------------- #


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
        events = load_events(conn, case_id)
    return {
        "case": case,
        "proposals": [dict(p) for p in proposals],
        "actions": [dict(a) for a in actions],
        "orders": [dict(o) for o in orders],
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
    p = st["proposals"][-1]
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
    return Check(q, True, f"Consulted {len(used)} distinct tools including {', '.join(required)}.")


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
    p = st["proposals"][-1]
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
    if len(completed) > 1:
        return Check(q, False, f"{len(completed)} actions executed where one was expected.")
    return Check(q, True,
                 f"Action '{p['action_type']}'; {len(completed)} execution(s) recorded.")


def q5_validated_result(fixture_id: str, expected: dict, st: dict) -> Check:
    q = "Did it validate the result?"
    completed = [a for a in st["actions"] if a["state"] == "completed"]
    if not completed:
        # Nothing executed, so there is nothing to validate. That is correct for
        # reject/escalate outcomes, not a gap.
        if expected.get("action_type") in ("none", "keep_plan", None):
            return Check(q, True, "No action executed, so no outcome required validation.")
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
        # Lost response after a successful commit: exactly one order must exist.
        count = len(st["orders"])
        want = expected.get("expected_po_count_after_retry", 1)
        ok = count == want
        return Check(q, ok,
                     f"After the timeout and recovery, {count} purchase order(s) exist "
                     f"(expected {want}). No duplicate created." if ok
                     else f"{count} orders exist; expected {want}.")

    partials = [json.loads(a["verdict_json"])["verdict"] for a in st["actions"]
                if a["verdict_json"]]
    if any(v in ("PARTIAL", "FAIL") for v in partials):
        reopened = case["replan_count"] > 0 or case["state"] in ("reopened", "escalated")
        return Check(q, reopened,
                     f"Verdict {partials} and the case moved to '{case['state']}' "
                     f"(replans: {case['replan_count']})." if reopened
                     else f"Verdict {partials} but the case did not reopen.")

    if case["state"] == "escalated":
        return Check(q, True, "No feasible option existed; escalated rather than acting.")
    return Check(q, True, f"Action succeeded; case state '{case['state']}'.")


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

        if record and live and isinstance(provider, RecordingProvider):
            provider.save()

        # Approve anything the gate held back, so the evaluation exercises the
        # full path through execution and validation rather than stopping at the
        # approval boundary.
        _auto_approve(case_id)

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
        try:
            if needs_approval:
                approve(case_id, proposal_id, approver="eval-harness")
            else:
                from app.services.proposals import authorize_and_execute
                authorize_and_execute(case_id, proposal_id)
        except Exception:
            # A refusal here is often the correct behaviour (blocked plan, stale
            # state). The checks below judge the outcome; this only drives it.
            pass


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
        "| Fixture | Mode | Model | Outcome | Tool calls | Result |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        verdict = "PASS" if r.passed else "FAIL"
        lines.append(
            f"| {r.fixture_id} | {r.mode} | {r.model or '-'} | {r.outcome or r.error[:40]} "
            f"| {r.tool_calls} | **{verdict}** |"
        )

    if questions:
        lines += ["", "## Per-question results", "",
                  "| Fixture | " + " | ".join(f"Q{i+1}" for i in range(len(questions))) + " |",
                  "|---" * (len(questions) + 1) + "|"]
        for r in results:
            cells = ["PASS" if c.passed else "FAIL" for c in r.checks] or ["-"] * len(questions)
            lines.append(f"| {r.fixture_id} | " + " | ".join(cells) + " |")
        lines += ["", "Legend:", ""]
        for i, q in enumerate(questions):
            lines.append(f"- **Q{i+1}** — {q}")

    lines += [
        "", "## Observations", "",
        "**Investigation paths are similar across fixtures.** The agent gathers all six "
        "evidence tools in roughly the same order every time rather than branching on "
        "what it finds. With a small, cheap evidence surface that is defensible -- there "
        "is little cost to reading everything -- but it means adaptivity shows up in the "
        "simulate-and-decide phase rather than in evidence gathering. Fixtures needing a "
        "specific comparison (F3, F4, F5, F6) issue a second targeted `simulate_plan` "
        "after the broad one; fixtures where the first answer is clear do not. "
        "Demonstrating branching during evidence gathering would need a larger or more "
        "expensive tool surface than this domain currently has.",
        "",
        "**The decisions do differ, which is the part that matters.** The same tool "
        "sweep produces reject-and-expedite, accept, modify-down, promotion-bounded "
        "buying, and escalate across the six fixtures.",
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
            lines.append(f"- {'PASS' if c.passed else 'FAIL'} — **{c.question}** {c.detail}")
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
