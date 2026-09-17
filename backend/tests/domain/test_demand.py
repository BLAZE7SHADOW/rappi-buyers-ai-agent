"""Demand evidence: promotion-bounded uplift and stockout-censored sales."""

from datetime import date, timedelta

from app.domain.demand import (
    analyze, average_sales, promotion_bounded_demand, split_censored, sustained_demand,
)
from app.domain.types import DemandDay, PolicyConfig, Promotion

TODAY = date(2026, 9, 17)


def history_with_spike():
    """14 days of sales at ~130/day against a 50/day forecast, with three of those
    days lost to a stockout."""
    out = []
    for i in range(14, 0, -1):
        day = TODAY - timedelta(days=i)
        censored = i in (11, 10, 9)
        out.append(DemandDay(
            day=day, forecast_units=50,
            actual_sales_units=0 if censored else 130,
            in_stock_pct=0.0 if censored else 1.0,
        ))
    return out


def forecast_days(n=28, units=50):
    return [DemandDay(day=TODAY + timedelta(days=i), forecast_units=units) for i in range(n)]


def test_censored_days_are_separated_from_usable_evidence():
    usable, censored = split_censored(history_with_spike())
    assert len(censored) == 3
    assert len(usable) == 11


def test_stockout_days_do_not_drag_the_observed_average_down():
    """Including zero-sale stockout days would understate demand by ~21%,
    exactly when the product is already short."""
    hist = history_with_spike()
    usable, _ = split_censored(hist)
    assert average_sales(usable) == 130.0
    assert average_sales(hist) < 103.0


def test_analysis_reports_both_the_spike_and_the_promotion():
    promo = Promotion("PROMO-1", "SKU-1004", TODAY - timedelta(days=10),
                      TODAY + timedelta(days=6), 2.6, "Launch push")
    result = analyze(history=history_with_spike(), forecast=forecast_days(),
                     promotions=[promo], today=TODAY)

    assert result["observed_daily_sales_excluding_censored"] == 130.0
    assert result["censored_day_count"] == 3
    assert result["ratio_to_forecast"] == 2.6
    assert result["active_promotion"]["days_remaining"] == 6
    assert any("stockout-censored" in f for f in result["findings"])
    assert any("should not be extrapolated" in f for f in result["findings"])


def test_uplift_stops_when_the_promotion_ends():
    promo = Promotion("PROMO-1", "SKU-1004", TODAY - timedelta(days=10),
                      TODAY + timedelta(days=6), 2.6, "Launch push")
    series = promotion_bounded_demand(
        forecast=forecast_days(), promotions=[promo],
        observed_daily=130.0, today=TODAY, policy=PolicyConfig(post_promo_uplift_factor=1.2),
    )
    assert series[TODAY] == 130                       # promotion still running
    assert series[TODAY + timedelta(days=6)] == 130   # final promotional day
    assert series[TODAY + timedelta(days=7)] == 60    # reverts to 50 * 1.2


def test_bounded_demand_is_far_below_naive_extrapolation():
    """The whole point of the fixture: extrapolating the promotional rate across
    the horizon roughly doubles the apparent need."""
    promo = Promotion("PROMO-1", "SKU-1004", TODAY - timedelta(days=10),
                      TODAY + timedelta(days=6), 2.6, "Launch push")
    fc = forecast_days()
    bounded = sum(promotion_bounded_demand(
        forecast=fc, promotions=[promo], observed_daily=130.0, today=TODAY).values())
    naive = sum(sustained_demand(forecast=fc, observed_daily=130.0).values())

    assert bounded == 910 + 1260   # 7 promo days at 130, then 21 days at 60
    assert naive == 3640
    assert naive > bounded * 1.6


def test_no_promotion_means_no_promotional_window():
    series = promotion_bounded_demand(
        forecast=forecast_days(), promotions=[], observed_daily=130.0, today=TODAY)
    assert set(series.values()) == {60}
