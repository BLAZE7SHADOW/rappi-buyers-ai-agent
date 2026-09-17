"""Does an unconfirmed input actually change the decision?

A buyer is sometimes told something the systems do not know: sales mention a
corporate order that is not booked, a supplier hints at a price move, marketing
plans a promotion that is not loaded yet. The question is never "is this
interesting" -- it is **would knowing the answer change what we buy**.

That question has an arithmetic answer, so it should not be left to judgement.
Plan the horizon twice, once with the unconfirmed signal and once without, and
compare the orders the two worlds require. If they differ materially, nobody can
responsibly place either order without asking first. If they do not, the signal is
worth recording as an assumption and nothing more.

Pure functions over dataclasses, like the rest of this layer: no database, no
model, no I/O. That is what lets the policy gate depend on this instead of on a
prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from app.domain.candidates import PlanningContext, required_quantity


@dataclass(frozen=True)
class UnverifiedSignal:
    """Demand someone has asserted but no system of record confirms."""

    units: int
    needed_by: date
    source: str = ""
    description: str = ""

    @classmethod
    def from_payload(cls, payload: dict | None) -> "UnverifiedSignal | None":
        """Read the signal off a case trigger, ignoring anything already confirmed.

        A confirmed signal belongs in the forecast, not here: once it is real it
        is ordinary demand and the normal machinery handles it.
        """
        if not payload or payload.get("confirmed"):
            return None
        try:
            units = int(payload.get("units") or 0)
            needed_by = payload["needed_by"]
        except (KeyError, TypeError, ValueError):
            return None
        if units <= 0:
            return None
        return cls(
            units=units,
            needed_by=date.fromisoformat(needed_by) if isinstance(needed_by, str) else needed_by,
            source=str(payload.get("source") or ""),
            description=str(payload.get("description") or ""),
        )


@dataclass(frozen=True)
class SensitivityResult:
    """What the two worlds require, and whether the gap is worth stopping for."""

    signal: UnverifiedSignal
    quantity_without: int
    quantity_with: int
    threshold_units: int
    material: bool

    @property
    def difference(self) -> int:
        return abs(self.quantity_with - self.quantity_without)

    def question(self) -> str:
        what = self.signal.description or f"{self.signal.units} additional units"
        source = f" ({self.signal.source})" if self.signal.source else ""
        return (
            f"Is {what}{source} confirmed? It is in no forecast, promotion or purchase "
            f"order, and the answer changes this order by {self.difference} units: "
            f"{self.quantity_without} units if it is not happening, "
            f"{self.quantity_with} if it is."
        )

    def options(self) -> list[str]:
        return [
            f"Not confirmed -- order {self.quantity_without} units for forecast demand only. "
            f"If it turns out to be real, that demand goes unserved.",
            f"Confirmed -- order {self.quantity_with} units to cover it as well. "
            f"If it never materialises, the extra stock sits as excess.",
        ]

    def to_dict(self) -> dict:
        return {
            "units": self.signal.units,
            "needed_by": self.signal.needed_by.isoformat(),
            "source": self.signal.source,
            "description": self.signal.description,
            "quantity_without": self.quantity_without,
            "quantity_with": self.quantity_with,
            "difference": self.difference,
            "threshold_units": self.threshold_units,
            "material": self.material,
        }


def _materiality_threshold(ctx: PlanningContext, baseline_qty: int) -> int:
    """The smallest difference worth interrupting a person for.

    Proportional to the order rather than a flat number, because 200 units means
    something very different on an order of 300 than on one of 30,000. The floor
    stops a tiny order from making every rounding difference an interruption.
    """
    policy = ctx.policy
    proportional = round(baseline_qty * policy.sensitivity_materiality_pct / 100)
    return max(policy.sensitivity_materiality_floor_units, proportional)


def evaluate(ctx: PlanningContext, signal: UnverifiedSignal | None) -> SensitivityResult | None:
    """Compare the order this plan needs with and without the unconfirmed signal."""
    if signal is None:
        return None

    without = required_quantity(ctx)

    # Apply the signal as extra demand on the day it would land. Using the
    # existing override hook keeps both worlds on identical arithmetic -- the
    # comparison is only meaningful if nothing else differs.
    same_day = next((d.forecast_units for d in ctx.demand if d.day == signal.needed_by), 0)
    with_signal = replace(
        ctx, demand_override={signal.needed_by: same_day + signal.units}
    )
    with_ = required_quantity(with_signal)

    threshold = _materiality_threshold(ctx, without)
    return SensitivityResult(
        signal=signal,
        quantity_without=without,
        quantity_with=with_,
        threshold_units=threshold,
        material=abs(with_ - without) >= threshold,
    )
