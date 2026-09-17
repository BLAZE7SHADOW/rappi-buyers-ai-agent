"""Demand evidence interpretation.

A forecast is a claim, not a fact. When recent sales disagree with it, the
question is *why* -- and the two most common answers point in opposite
directions:

* **Sales ran hot because a promotion is running.** The uplift is real but
  time-boxed. Extrapolating it past the promotion's end date over-buys.
* **Sales ran cold because the product was out of stock.** Those days are
  censored evidence: they measure availability, not demand. Reading them as low
  demand under-buys, and does so precisely when the product is already short.

This module makes both visible so the decision rests on evidence rather than on
a naive average.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.domain.types import DemandDay, PolicyConfig, Promotion


def split_censored(history: list[DemandDay]) -> tuple[list[DemandDay], list[DemandDay]]:
    """Separate usable sales days from stockout-censored ones."""
    usable = [d for d in history if not d.is_censored]
    censored = [d for d in history if d.is_censored]
    return usable, censored


def average_sales(history: list[DemandDay]) -> float:
    observed = [d.actual_sales_units for d in history if d.actual_sales_units is not None]
    if not observed:
        return 0.0
    return sum(observed) / len(observed)


def active_promotion(promotions: list[Promotion], day: date) -> Promotion | None:
    return next((p for p in promotions if p.covers(day)), None)


def analyze(
    *,
    history: list[DemandDay],
    forecast: list[DemandDay],
    promotions: list[Promotion],
    today: date,
    policy: PolicyConfig | None = None,
) -> dict:
    """Describe what the demand evidence supports, without deciding anything.

    Returns a plain dict so it can go straight into a tool result. The agent reads
    these findings; it does not invent its own demand numbers.
    """
    policy = policy or PolicyConfig()
    usable, censored = split_censored(history)

    observed_avg = average_sales(usable)
    raw_avg = average_sales(history)
    forecast_avg = (
        sum(d.forecast_units for d in forecast) / len(forecast) if forecast else 0.0
    )

    promo = active_promotion(promotions, today)
    ratio = (observed_avg / forecast_avg) if forecast_avg > 0 else 0.0

    findings: list[str] = []
    if censored:
        findings.append(
            f"{len(censored)} of the last {len(history)} days were stockout-censored "
            f"(zero availability). Those days measure availability, not demand, and are "
            f"excluded from the observed average."
        )
    if forecast_avg > 0 and ratio >= 1.2:
        findings.append(
            f"Observed sales average {observed_avg:.0f}/day against a forecast of "
            f"{forecast_avg:.0f}/day ({ratio:.1f}x). The forecast understates current demand."
        )
    elif forecast_avg > 0 and ratio <= 0.8 and not censored:
        findings.append(
            f"Observed sales average {observed_avg:.0f}/day against a forecast of "
            f"{forecast_avg:.0f}/day. The forecast overstates current demand."
        )
    if promo:
        findings.append(
            f"Promotion {promo.promotion_id} ({promo.label}) is active until "
            f"{promo.end_date.isoformat()}. Elevated sales are at least partly "
            f"promotional and should not be extrapolated past that date."
        )

    return {
        "observed_daily_sales_excluding_censored": round(observed_avg, 1),
        "observed_daily_sales_raw": round(raw_avg, 1),
        "forecast_daily_units": round(forecast_avg, 1),
        "ratio_to_forecast": round(ratio, 2),
        "censored_days": [d.day.isoformat() for d in censored],
        "censored_day_count": len(censored),
        "active_promotion": (
            {
                "promotion_id": promo.promotion_id,
                "label": promo.label,
                "start_date": promo.start_date.isoformat(),
                "end_date": promo.end_date.isoformat(),
                "uplift_factor": promo.uplift_factor,
                "days_remaining": max(0, (promo.end_date - today).days),
            }
            if promo else None
        ),
        "findings": findings,
    }


def promotion_bounded_demand(
    *,
    forecast: list[DemandDay],
    promotions: list[Promotion],
    observed_daily: float,
    today: date,
    policy: PolicyConfig | None = None,
) -> dict[date, int]:
    """Build an adjusted demand series bounded by the promotion's end date.

    While a promotion runs, the observed rate is used. After it ends, demand falls
    back to the forecast with a modest documented residual uplift rather than
    either the promotional rate (over-buying) or the untouched forecast
    (ignoring the evidence).

    The residual factor is configuration, not a prediction, and is reported as an
    assumption on any proposal that relies on it.
    """
    policy = policy or PolicyConfig()
    promo = active_promotion(promotions, today)
    out: dict[date, int] = {}

    for d in forecast:
        if promo and promo.covers(d.day):
            out[d.day] = int(round(observed_daily))
        else:
            out[d.day] = int(round(d.forecast_units * policy.post_promo_uplift_factor))
    return out


def sustained_demand(
    *, forecast: list[DemandDay], observed_daily: float
) -> dict[date, int]:
    """The naive alternative: assume the elevated rate holds for the whole horizon.

    Kept as an explicit, comparable option so the difference between "the spike is
    promotional" and "the spike is the new normal" is a decision with visible
    consequences rather than a hidden assumption.
    """
    return {d.day: int(round(observed_daily)) for d in forecast}
