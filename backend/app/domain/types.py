"""Core domain types.

Conventions used throughout the domain layer:

* **Money** is always an integer count of minor units (cents). There are no floats
  anywhere in the money path, so totals are exact and comparisons are safe.
* **Quantities** are always whole units.
* **Dates** are ``datetime.date`` in the node's local timezone. The model resolution
  is one day; intraday timing is explicitly out of scope.

Everything in this module is a plain dataclass with no database, network, or LLM
dependency. That is what makes the domain engine unit-testable in isolation and is
the structural reason the agent cannot get the arithmetic wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

Minor = int  # integer minor currency units (cents)


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class Disposition(str, Enum):
    """The agent's judgement on the *incoming recommendation*.

    Deliberately separate from :class:`ActionType`: rejecting a proposed 800-unit
    order can still lead to expediting an existing one.
    """

    ACCEPT = "accept"
    MODIFY = "modify"
    REJECT = "reject"
    INVESTIGATE = "investigate"
    ESCALATE = "escalate"


class ActionType(str, Enum):
    """The intervention to perform. Exactly three levers exist, plus "do nothing"."""

    KEEP_PLAN = "keep_plan"
    CREATE_PO = "create_po"
    EXPEDITE_PO = "expedite_po"
    NONE = "none"


class CaseState(str, Enum):
    INVESTIGATING = "investigating"
    AWAITING_BUYER = "awaiting_buyer"
    PROPOSED = "proposed"
    AWAITING_APPROVAL = "awaiting_approval"
    AUTHORIZED = "authorized"
    EXECUTING = "executing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    VALIDATING = "validating"
    RESOLVED = "resolved"
    REOPENED = "reopened"
    ESCALATED = "escalated"
    PENDING_INVESTIGATION = "pending_investigation"


class POStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    PARTIALLY_CONFIRMED = "partially_confirmed"
    CANCELLED = "cancelled"
    RECEIVED = "received"


class VerdictKind(str, Enum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class EventKind(str, Enum):
    TOOL_CALL = "tool_call"
    OBSERVATION = "observation"
    PROPOSAL = "proposal"
    QUESTION = "question"
    ANSWER = "answer"
    APPROVAL = "approval"
    ACTION = "action"
    VERDICT = "verdict"
    STATE = "state"
    ERROR = "error"


# --------------------------------------------------------------------------- #
# Evidence inputs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class InventoryPosition:
    """On-hand stock decomposed into usable and unusable buckets."""

    sku: str
    node_id: str
    on_hand: int
    reserved: int
    quarantine: int
    damaged: int
    effective_at: date
    version: int = 1

    @property
    def usable(self) -> int:
        """Stock actually available to serve future demand.

        Reserved, quarantined and damaged units are excluded. Future demand must
        therefore also exclude the commitments those reservations represent, or the
        same units get counted twice.
        """
        return max(0, self.on_hand - self.reserved - self.quarantine - self.damaged)


@dataclass(frozen=True)
class DemandDay:
    """One day of demand evidence.

    ``in_stock_pct`` is what makes stockout-censored sales detectable: a day with
    zero sales and zero availability is *missing* evidence, not evidence of zero
    demand.
    """

    day: date
    forecast_units: int
    actual_sales_units: int | None = None
    in_stock_pct: float | None = None
    promotion_id: str | None = None

    @property
    def is_censored(self) -> bool:
        return self.in_stock_pct is not None and self.in_stock_pct <= 0.0


@dataclass(frozen=True)
class Promotion:
    promotion_id: str
    sku: str
    start_date: date
    end_date: date
    uplift_factor: float
    label: str = ""

    def covers(self, day: date) -> bool:
        return self.start_date <= day <= self.end_date


@dataclass(frozen=True)
class Receipt:
    """Incoming supply landing on a given day.

    ``confirmed`` distinguishes supply that may enter the baseline projection from
    supply that is merely expected. Unconfirmed or overdue receipts surface as an
    explicit uncertainty rather than being silently counted.
    """

    day: date
    qty: int
    po_id: str | None = None
    confirmed: bool = True


@dataclass(frozen=True)
class OpenOrder:
    po_id: str
    sku: str
    node_id: str
    supplier_id: str
    requested_qty: int
    confirmed_qty: int
    received_qty: int
    cancelled_qty: int
    requested_date: date
    confirmed_date: date | None
    status: POStatus
    acknowledged_at: date | None = None
    version: int = 1

    @property
    def outstanding_qty(self) -> int:
        """Units still owed by the supplier.

        Convention: ``confirmed_qty`` is the *net* quantity the supplier has
        committed to and already excludes anything cancelled. Subtracting
        ``cancelled_qty`` from it again would double-count the shortfall and
        understate incoming supply -- which in turn overstates the shortage and
        drives an unnecessary second order.

        Only when there is no confirmation does the requested quantity apply, and
        there cancellations do still need netting out.
        """
        if self.confirmed_qty > 0:
            return max(0, self.confirmed_qty - self.received_qty)
        return max(0, self.requested_qty - self.received_qty - self.cancelled_qty)

    def is_overdue(self, today: date) -> bool:
        due = self.confirmed_date or self.requested_date
        return self.outstanding_qty > 0 and due < today

    @property
    def is_acknowledged(self) -> bool:
        return self.acknowledged_at is not None and self.confirmed_date is not None


@dataclass(frozen=True)
class SupplierQuote:
    supplier_id: str
    sku: str
    unit_price_minor: Minor
    moq: int
    pack_size: int
    lead_time_days: int
    available_units: int
    quote_expires_at: date
    eligible: bool = True
    expedite_available: bool = False
    expedite_fee_minor: Minor = 0
    expedite_days_saved: int = 0

    def is_expired(self, today: date) -> bool:
        return self.quote_expires_at < today


# --------------------------------------------------------------------------- #
# Constraints
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Budget:
    scope: str
    period: str
    limit_minor: Minor
    committed_minor: Minor
    reserved_minor: Minor
    version: int = 1

    @property
    def available_minor(self) -> Minor:
        """Spendable headroom. Reservations count against it so two concurrent
        cases cannot both claim the same funds."""
        return self.limit_minor - self.committed_minor - self.reserved_minor


@dataclass(frozen=True)
class CapacityDay:
    day: date
    capacity_m3: float
    occupied_m3: float
    inbound_m3: float = 0.0

    @property
    def headroom_m3(self) -> float:
        return self.capacity_m3 - self.occupied_m3 - self.inbound_m3


@dataclass(frozen=True)
class PolicyConfig:
    """Demo purchasing policy. These are configuration, not universal rules."""

    horizon_days: int = 28
    safety_stock_units: int = 200
    max_days_cover: int = 12
    zero_demand_unit_cap: int = 100
    autonomy_spend_limit_minor: Minor = 200_000
    autonomy_fee_limit_minor: Minor = 25_000
    max_tool_calls: int = 12
    max_replans: int = 2
    post_promo_uplift_factor: float = 1.2


# --------------------------------------------------------------------------- #
# Projection output
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProjectionDay:
    day: date
    opening: int
    receipts: int
    available: int
    demand: int
    served: int
    unmet: int
    closing: int
    below_safety: bool


@dataclass(frozen=True)
class Projection:
    days: list[ProjectionDay]
    total_demand_units: int
    total_unmet_units: int
    first_stockout_date: date | None
    days_below_safety: int
    closing_inventory: int
    peak_occupancy_m3: float = 0.0

    @property
    def has_shortage(self) -> bool:
        return self.total_unmet_units > 0


# --------------------------------------------------------------------------- #
# Candidates, constraints, simulation
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Candidate:
    """A proposed intervention, before feasibility is known."""

    action_type: ActionType
    supplier_id: str | None = None
    qty: int = 0
    expected_receipt_date: date | None = None
    po_id: str | None = None
    new_date: date | None = None
    unit_price_minor: Minor = 0
    fee_minor: Minor = 0
    label: str = ""

    @property
    def total_cost_minor(self) -> Minor:
        return self.qty * self.unit_price_minor + self.fee_minor


@dataclass(frozen=True)
class ConstraintCheck:
    """One hard-constraint verdict.

    ``binding_reason`` is always human-readable: it is what the UI shows next to an
    infeasible option and what the agent quotes when explaining a rejection.
    """

    name: str
    passed: bool
    binding_reason: str = ""
    limit: float | int | None = None
    required: float | int | None = None


@dataclass(frozen=True)
class SimulationResult:
    """The single source of numbers. The LLM never computes these itself."""

    candidate: Candidate
    before: Projection
    after: Projection
    checks: list[ConstraintCheck]
    incremental_cost_minor: Minor

    @property
    def feasible(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def binding_constraints(self) -> list[str]:
        return [c.name for c in self.checks if not c.passed]

    @property
    def unmet_reduction(self) -> int:
        return self.before.total_unmet_units - self.after.total_unmet_units

    @property
    def residual_unmet(self) -> int:
        return self.after.total_unmet_units


@dataclass
class Verdict:
    """The output of independent post-execution validation.

    This object is the tangible answer to "how did you design the feedback loop".
    It is produced by code that never sees the agent's claims, and a ``PARTIAL`` or
    ``FAIL`` result reopens the case rather than being reported as success.
    """

    verdict: VerdictKind
    expected: dict
    actual: dict
    deltas: dict = field(default_factory=dict)
    checks: list[dict] = field(default_factory=list)
    residual_exposure: dict = field(default_factory=dict)
    follow_up: str = ""

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "expected": self.expected,
            "actual": self.actual,
            "deltas": self.deltas,
            "checks": self.checks,
            "residual_exposure": self.residual_exposure,
            "follow_up": self.follow_up,
        }
