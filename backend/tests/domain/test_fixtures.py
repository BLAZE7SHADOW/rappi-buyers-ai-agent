"""Verifies every seed fixture against the real domain engine.

Each fixture in ``fixtures.FIXTURES`` carries an ``expected`` dict -- the one
place its intended outcome is recorded (read by this file, and by any eval
harness that wants the same numbers). This file seeds each fixture into an
isolated database, rebuilds the ``PlanningContext`` the same way a live case
would, and asserts the engine (``app.domain.candidates`` / ``projection`` /
``demand``) actually produces that outcome. Nothing here hand-computes an
expected number independently of the fixture's own ``expected`` dict; if a
number needed adjusting, the fixture's numbers and its ``expected`` dict were
changed together so this file is always checking engine output against the
single recorded intent.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.domain.candidates import (
    PlanningContext, baseline_projection, best, rank, required_quantity, simulate_all,
)
from app.domain.demand import analyze, promotion_bounded_demand, sustained_demand
from app.domain.types import ActionType, PolicyConfig
from fixtures import ANCHOR, FIXTURES


# --------------------------------------------------------------------------- #
# Isolated database per test
# --------------------------------------------------------------------------- #


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/fixtures_{uuid.uuid4().hex[:6]}.db")

    import app.config as config
    config.get_settings.cache_clear()

    import app.db.engine as engine_mod
    engine_mod._engine = None
    engine_mod.create_all()

    yield engine_mod

    engine_mod._engine = None
    config.get_settings.cache_clear()


def _load_context(conn, sku: str, node_id: str) -> PlanningContext:
    """Rebuild a PlanningContext from the DB exactly as a live case would."""
    from app.db import repo

    product = repo.load_product(conn, sku)
    inventory = repo.load_inventory(conn, sku, node_id)
    policy = PolicyConfig()
    demand = repo.load_demand(conn, sku, node_id, ANCHOR, policy.horizon_days)
    open_orders = repo.load_open_orders(conn, sku, node_id)
    quotes = repo.load_quotes(conn, sku)
    budget = repo.load_budget(conn, node_id, ANCHOR.strftime("%Y-%m"))
    capacity = repo.load_capacity(conn, node_id, ANCHOR, policy.horizon_days)
    return PlanningContext(
        sku=sku, node_id=node_id, today=ANCHOR,
        inventory=inventory, demand=demand, open_orders=open_orders,
        quotes=quotes, budget=budget, capacity=capacity,
        unit_volume_m3=product["unit_volume_m3"], policy=policy,
    )


def _seed(db, fixture_id: str):
    from app.db.seed import seed_fixture
    return seed_fixture(fixture_id)


# --------------------------------------------------------------------------- #
# F1 -- headline: reject 800 on budget, expedite PO-501 instead
# --------------------------------------------------------------------------- #


def test_f1_headline(db):
    fx = FIXTURES["F1"]
    exp = fx.expected
    case_id = _seed(db, "F1")
    assert case_id == fx.case_id

    from app.db.engine import transaction
    with transaction() as conn:
        ctx = _load_context(conn, fx.sku, fx.node_id)

    before = baseline_projection(ctx)
    assert before.total_unmet_units == exp["baseline_unmet"]
    assert before.first_stockout_date.isoformat() == exp["first_stockout"]

    results = simulate_all(ctx, recommended_qty=exp["recommended_qty"])
    ranked = rank(results)

    # The recommended 800-unit purchase is rejected on budget alone.
    eight = next(
        r for r in results
        if r.candidate.action_type == ActionType.CREATE_PO and r.candidate.qty == 800
    )
    assert eight.feasible is False
    assert eight.binding_constraints == exp["recommended_800_binding_constraints"]

    # The winning plan expedites PO-501, not a new purchase.
    top = ranked[0]
    assert top.candidate.action_type == ActionType.EXPEDITE_PO
    assert top.candidate.po_id == exp["po_id"]
    assert top.candidate.new_date.isoformat() == exp["expedite_new_date"]
    assert top.candidate.fee_minor == exp["expedite_fee_minor"]
    assert top.after.total_unmet_units == exp["after_unmet"]

    # The fee exceeds the autonomy limit, so buyer approval is required.
    assert top.candidate.fee_minor > exp["autonomy_fee_limit_minor"]
    assert exp["approval_required"] is True


# --------------------------------------------------------------------------- #
# F2 -- accept: 800 is exactly right
# --------------------------------------------------------------------------- #


def test_f2_accept(db):
    fx = FIXTURES["F2"]
    exp = fx.expected
    _seed(db, "F2")

    from app.db.engine import transaction
    with transaction() as conn:
        ctx = _load_context(conn, fx.sku, fx.node_id)

    before = baseline_projection(ctx)
    assert before.total_unmet_units == exp["baseline_unmet"]
    assert required_quantity(ctx) == exp["required_quantity"] == exp["recommended_qty"]

    results = simulate_all(ctx, recommended_qty=exp["recommended_qty"])
    eight = next(
        r for r in results
        if r.candidate.action_type == ActionType.CREATE_PO and r.candidate.qty == exp["qty"]
    )
    assert eight.feasible is exp["feasible"]
    assert eight.incremental_cost_minor == exp["cost_minor"]
    assert eight.after.total_unmet_units == exp["after_unmet"]

    top = best(results)
    assert top is not None
    assert top.candidate.action_type == ActionType.CREATE_PO
    assert top.candidate.qty == exp["qty"]


# --------------------------------------------------------------------------- #
# F3 -- modify down: capacity and demand both cap the order below 800
# --------------------------------------------------------------------------- #


def test_f3_modify_down(db):
    fx = FIXTURES["F3"]
    exp = fx.expected
    _seed(db, "F3")

    from app.db.engine import transaction
    with transaction() as conn:
        ctx = _load_context(conn, fx.sku, fx.node_id)

    before = baseline_projection(ctx)
    assert before.total_unmet_units == exp["baseline_unmet"]
    assert before.first_stockout_date.isoformat() == exp["first_stockout"]
    assert required_quantity(ctx) == exp["required_quantity"]

    results = simulate_all(ctx, recommended_qty=exp["recommended_qty"])

    eight = next(
        r for r in results
        if r.candidate.action_type == ActionType.CREATE_PO and r.candidate.qty == 800
    )
    assert eight.feasible is False
    assert set(eight.binding_constraints) == set(exp["recommended_800_binding_constraints"])

    top = best(results)
    assert top is not None
    assert top.candidate.action_type == ActionType.CREATE_PO
    lo, hi = exp["qty_band"]
    assert lo <= top.candidate.qty <= hi
    assert top.candidate.qty == exp["qty"]
    assert top.candidate.qty < exp["recommended_qty"]  # a genuine modification, not a rubber stamp
    assert top.after.total_unmet_units == exp["after_unmet"]


# --------------------------------------------------------------------------- #
# F4 -- demand spike + stockout-censored trap
# --------------------------------------------------------------------------- #


def test_f4_demand_spike_evidence(db):
    fx = FIXTURES["F4"]
    exp = fx.expected
    _seed(db, "F4")

    from app.db import repo
    from app.db.engine import transaction

    with transaction() as conn:
        history = repo.load_sales_history(conn, fx.sku, fx.node_id, ANCHOR, 14)
        forecast = repo.load_demand(conn, fx.sku, fx.node_id, ANCHOR, 28)
        promotions = repo.load_promotions(conn, fx.sku)

    result = analyze(history=history, forecast=forecast, promotions=promotions, today=ANCHOR)

    assert result["censored_day_count"] == exp["censored_day_count"]
    assert result["censored_days"] == exp["censored_days"]
    assert result["observed_daily_sales_excluding_censored"] == exp["observed_daily_sales_excluding_censored"]
    assert result["forecast_daily_units"] == exp["forecast_daily_units"]
    assert result["active_promotion"] is not None
    assert result["active_promotion"]["promotion_id"] == exp["active_promotion_id"]
    assert result["active_promotion"]["end_date"] == exp["promotion_end_date"]

    bounded = promotion_bounded_demand(
        forecast=forecast, promotions=promotions,
        observed_daily=result["observed_daily_sales_excluding_censored"], today=ANCHOR,
    )
    naive = sustained_demand(
        forecast=forecast, observed_daily=result["observed_daily_sales_excluding_censored"],
    )

    assert sum(bounded.values()) == exp["promotion_bounded_total_demand"]
    assert sum(naive.values()) == exp["naive_sustained_total_demand"]
    # The whole point of the fixture: bounded demand must be well below the
    # naive "extrapolate the spike forever" number.
    assert sum(bounded.values()) < sum(naive.values())


# --------------------------------------------------------------------------- #
# F5 -- recovery: same engine outcome as F1, plus the retry never duplicates
# --------------------------------------------------------------------------- #


def test_f5_recovery_same_decision_as_f1(db):
    fx = FIXTURES["F5"]
    exp = fx.expected
    _seed(db, "F5")

    from app.db.engine import transaction
    with transaction() as conn:
        ctx = _load_context(conn, fx.sku, fx.node_id)

    before = baseline_projection(ctx)
    assert before.total_unmet_units == exp["baseline_unmet"]
    assert before.first_stockout_date.isoformat() == exp["first_stockout"]

    ranked = rank(simulate_all(ctx, recommended_qty=800))
    top = ranked[0]
    assert top.candidate.action_type == ActionType.EXPEDITE_PO
    assert top.candidate.po_id == exp["po_id"]
    assert top.after.total_unmet_units == exp["after_unmet"]


def test_f5_idempotency_key_rejects_a_duplicate_action(db):
    """The mechanism F5's expected recovery behaviour depends on: retrying an
    ambiguous action must not be able to create a second row for it. This is
    enforced at the schema level by ``actions.idempotency_key`` UNIQUE -- prove
    it directly rather than just asserting the fixture says so.
    """
    fx = FIXTURES["F5"]
    assert fx.expected["expected_po_count_after_retry"] == 1

    from app.db import schema as s
    from app.db.engine import transaction

    key = f"idem-{fx.case_id}"

    with transaction() as conn:
        conn.execute(s.actions.insert().values(
            action_id="ACT-1", case_id=fx.case_id, proposal_id="PROP-1",
            proposal_version=1, action_type="expedite_po", idempotency_key=key,
            request_json="{}", state="pending", attempts=1,
        ))

    with pytest.raises(IntegrityError):
        with transaction() as conn:
            conn.execute(s.actions.insert().values(
                action_id="ACT-2", case_id=fx.case_id, proposal_id="PROP-1",
                proposal_version=1, action_type="expedite_po", idempotency_key=key,
                request_json="{}", state="pending", attempts=1,
            ))

    with transaction() as conn:
        rows = conn.execute(s.actions.select()).mappings().all()
    assert len(rows) == 1


# --------------------------------------------------------------------------- #
# F6 -- escalate: genuine shortfall, nothing affordable
# --------------------------------------------------------------------------- #


def test_f6_escalate(db):
    fx = FIXTURES["F6"]
    exp = fx.expected
    _seed(db, "F6")

    from app.db.engine import transaction
    with transaction() as conn:
        ctx = _load_context(conn, fx.sku, fx.node_id)

    before = baseline_projection(ctx)
    assert before.total_unmet_units == exp["baseline_unmet"]
    assert ctx.budget.available_minor == exp["budget_available_minor"]

    results = simulate_all(ctx, recommended_qty=exp["recommended_qty"])
    for r in results:
        if r.candidate.action_type == ActionType.CREATE_PO:
            assert r.feasible is False
            assert "budget" in r.binding_constraints

    top = best(results)
    assert top is not None
    assert top.candidate.action_type == ActionType.KEEP_PLAN
    assert top.after.total_unmet_units == exp["baseline_unmet"]
    # No feasible paid lever exists -- this is what makes "escalate" / action
    # "none" the correct call rather than a fabricated purchase.
    assert all(
        r.feasible is False
        for r in results
        if r.candidate.action_type in (ActionType.CREATE_PO, ActionType.EXPEDITE_PO)
    )
