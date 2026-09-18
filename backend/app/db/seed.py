"""Load the demo/eval fixtures into the database.

Fixture data itself lives in ``fixtures/`` at the repo root -- that package is
the single source of truth for the numbers; this module only knows how to turn
a :class:`fixtures.Fixture` into rows in the tables declared by
``app.db.schema``.

Run directly with::

    python -m app.db.seed

which resets the database and loads all eight fixtures, printing one summary
line per fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ``fixtures`` lives at the repo root, one level above ``backend/``. Make sure
# it is importable regardless of the current working directory.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy.engine import Connection

from app.db import schema as s
from app.db.engine import reset_database, transaction
from fixtures import FIXTURES, Fixture


def _dedupe(rows: list[dict], key: str) -> list[dict]:
    """Keep the first row seen for each value of ``key``.

    Some entities (suppliers, in particular) are the same real-world thing
    across multiple fixtures and must only be inserted once per key column.
    """
    seen: set = set()
    out: list[dict] = []
    for row in rows:
        k = row[key]
        if k in seen:
            continue
        seen.add(k)
        out.append(row)
    return out


def _insert_fixture(conn: Connection, fx: Fixture) -> None:
    if fx.products:
        conn.execute(s.products.insert(), fx.products)
    if fx.nodes:
        conn.execute(s.nodes.insert(), fx.nodes)
    if fx.inventory_snapshots:
        conn.execute(s.inventory_snapshots.insert(), fx.inventory_snapshots)
    if fx.demand_records:
        conn.execute(s.demand_records.insert(), fx.demand_records)
    if fx.promotions:
        conn.execute(s.promotions.insert(), fx.promotions)
    if fx.suppliers:
        conn.execute(s.suppliers.insert(), fx.suppliers)
    if fx.supplier_quotes:
        conn.execute(s.supplier_quotes.insert(), fx.supplier_quotes)
    if fx.purchase_orders:
        conn.execute(s.purchase_orders.insert(), fx.purchase_orders)
    if fx.budgets:
        conn.execute(s.budgets.insert(), fx.budgets)
    if fx.capacity_projections:
        conn.execute(s.capacity_projections.insert(), fx.capacity_projections)
    conn.execute(s.cases.insert().values(**fx.case))


def seed_fixture(fixture_id: str) -> str:
    """Load one fixture into the current database and return its case_id.

    Suppliers are deduplicated against whatever is already in the database
    (by primary key) so this can be called repeatedly, including after
    ``seed_all``, without violating the ``suppliers`` primary key.
    """
    fx = FIXTURES[fixture_id]
    with transaction() as conn:
        existing_suppliers = {
            row.supplier_id for row in conn.execute(s.suppliers.select())
        }
        fx_for_insert = fx
        new_suppliers = [r for r in fx.suppliers if r["supplier_id"] not in existing_suppliers]
        if new_suppliers != fx.suppliers:
            fx_for_insert = Fixture(
                **{**fx.__dict__, "suppliers": new_suppliers}
            )
        _insert_fixture(conn, fx_for_insert)
    return fx.case["case_id"]


def seed_all(reset: bool = True) -> None:
    """Wipe (if ``reset``) and load every fixture in ``FIXTURES``.

    Suppliers are shared real-world entities (``SUP-A``, ``SUP-B``) reused
    across fixtures, so they are deduplicated once across the whole batch and
    inserted a single time each; every other table is scoped per fixture
    (each fixture gets its own node, budget and capacity projections) so
    fixtures never collide with one another.
    """
    if reset:
        reset_database()

    all_suppliers = _dedupe(
        [row for fx in FIXTURES.values() for row in fx.suppliers], "supplier_id"
    )

    with transaction() as conn:
        if all_suppliers:
            conn.execute(s.suppliers.insert(), all_suppliers)
        for fx in FIXTURES.values():
            fx_no_suppliers = Fixture(**{**fx.__dict__, "suppliers": []})
            _insert_fixture(conn, fx_no_suppliers)


def _print_summary() -> None:
    with transaction() as conn:
        for fixture_id, fx in FIXTURES.items():
            case = conn.execute(
                s.cases.select().where(s.cases.c.case_id == fx.case["case_id"])
            ).mappings().first()
            state = case["state"] if case else "MISSING"
            print(
                f"{fixture_id}: case={fx.case['case_id']} sku={fx.sku} node={fx.node_id} "
                f"state={state} expected_disposition={fx.expected.get('disposition', '-')}"
            )


def main() -> None:
    seed_all(reset=True)
    _print_summary()


if __name__ == "__main__":
    main()
