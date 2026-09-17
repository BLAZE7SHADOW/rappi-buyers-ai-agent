"""Policy gate: decides whether an action may execute, and on whose authority.

Three outcomes, and the distinction between them matters:

* **BLOCKED** -- a hard constraint fails. Budget and capacity are financial and
  physical facts; no approval button can waive them. Resolving these requires
  recording new budget or new space and revalidating.
* **APPROVAL_REQUIRED** -- feasible, but outside delegated authority. A human
  decides.
* **AUTONOMOUS** -- feasible and within limits. Executes without a human.

The gate runs server-side and is the only path to execution. The agent has no
tool that can reach the executor directly, so "the agent cannot approve its own
action" is a property of the architecture rather than a promise about prompting.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.config import get_settings
from app.domain.types import ActionType, SimulationResult


class GateOutcome(str, Enum):
    AUTONOMOUS = "autonomous"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"


@dataclass
class GateDecision:
    outcome: GateOutcome
    reason: str
    triggers: list[str]

    @property
    def approval_required(self) -> bool:
        return self.outcome is GateOutcome.APPROVAL_REQUIRED

    @property
    def blocked(self) -> bool:
        return self.outcome is GateOutcome.BLOCKED

    def to_dict(self) -> dict:
        return {"outcome": self.outcome.value, "reason": self.reason, "triggers": self.triggers}


def evaluate(
    simulation: SimulationResult,
    *,
    missing_evidence: list[str] | None = None,
    spend_limit_minor: int | None = None,
    fee_limit_minor: int | None = None,
) -> GateDecision:
    """Apply the gate to one simulated candidate."""
    settings = get_settings()
    spend_limit = (
        spend_limit_minor if spend_limit_minor is not None
        else settings.autonomy_spend_limit_minor
    )
    fee_limit = (
        fee_limit_minor if fee_limit_minor is not None
        else settings.autonomy_fee_limit_minor
    )
    missing = missing_evidence or []
    candidate = simulation.candidate

    # Doing nothing is always permitted: it spends nothing and changes nothing.
    if candidate.action_type in (ActionType.KEEP_PLAN, ActionType.NONE):
        return GateDecision(GateOutcome.AUTONOMOUS, "No action to authorise.", [])

    # Hard constraints first. These are not negotiable through approval.
    if not simulation.feasible:
        failed = [c for c in simulation.checks if not c.passed]
        reasons = "; ".join(c.binding_reason for c in failed)
        return GateDecision(
            GateOutcome.BLOCKED,
            f"Hard constraint not satisfied: {reasons} "
            f"This cannot be authorised by approval; the underlying constraint must change.",
            [c.name for c in failed],
        )

    triggers: list[str] = []

    # Decision-critical unknowns block automatic execution. Missing data is not zero.
    if missing:
        triggers.append("missing_evidence")

    cost = candidate.total_cost_minor
    if cost > spend_limit:
        triggers.append("spend_above_autonomy_limit")

    if candidate.fee_minor > fee_limit:
        triggers.append("fee_above_autonomy_limit")

    # An action that leaves demand unserved is a partial mitigation, not a fix,
    # so a human should agree to accept the residual exposure.
    if simulation.residual_unmet > 0:
        triggers.append("residual_unmet_demand")

    if not triggers:
        return GateDecision(
            GateOutcome.AUTONOMOUS,
            f"Within delegated authority: {_money(cost)} spend, "
            f"{_money(candidate.fee_minor)} fees, no residual shortage.",
            [],
        )

    return GateDecision(GateOutcome.APPROVAL_REQUIRED, _explain(triggers, candidate, simulation,
                                                                spend_limit, fee_limit, missing),
                        triggers)


def _money(minor: int) -> str:
    return f"${minor / 100:,.2f}"


def _explain(triggers, candidate, simulation, spend_limit, fee_limit, missing) -> str:
    parts: list[str] = []
    if "spend_above_autonomy_limit" in triggers:
        parts.append(
            f"spend of {_money(candidate.total_cost_minor)} exceeds the "
            f"{_money(spend_limit)} autonomy limit"
        )
    if "fee_above_autonomy_limit" in triggers:
        parts.append(
            f"expedite fee of {_money(candidate.fee_minor)} exceeds the "
            f"{_money(fee_limit)} fee limit"
        )
    if "residual_unmet_demand" in triggers:
        parts.append(
            f"{simulation.residual_unmet} units of demand remain unserved after this action"
        )
    if "missing_evidence" in triggers:
        parts.append("decision-critical evidence is missing: " + ", ".join(missing))
    return "Buyer approval required because " + "; ".join(parts) + "."
