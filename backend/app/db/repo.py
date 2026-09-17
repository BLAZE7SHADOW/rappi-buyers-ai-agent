"""Repository layer: the only place SQL rows become domain objects.

Keeping the mapping here means the domain engine only ever sees plain dataclasses,
and the agent tools only ever see JSON -- neither touches SQL directly.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from app.db import schema as s
from app.domain.types import (
    Budget,
    CapacityDay,
    DemandDay,
    EventKind,
    InventoryPosition,
    OpenOrder,
    POStatus,
    Promotion,
    SupplierQuote,
)


# --------------------------------------------------------------------------- #
# Event log (append-only)
# --------------------------------------------------------------------------- #


def append_event(
    conn: Connection,
    case_id: str,
    kind: EventKind | str,
    label: str = "",
    payload: dict | None = None,
) -> int:
    """Append one immutable entry to a case's history and return its sequence.

    Sequence numbers are allocated per case from the existing max, so the timeline
    is totally ordered even when timestamps collide.
    """
    kind_value = kind.value if isinstance(kind, EventKind) else str(kind)
    next_seq = (
        conn.execute(
            select(func.coalesce(func.max(s.case_events.c.seq), 0)).where(
                s.case_events.c.case_id == case_id
            )
        ).scalar_one()
        + 1
    )
    conn.execute(
        s.case_events.insert().values(
            case_id=case_id,
            seq=next_seq,
            kind=kind_value,
            label=label,
            payload_json=json.dumps(payload or {}, default=str),
        )
    )
    return next_seq


def load_events(conn: Connection, case_id: str) -> list[dict]:
    rows = conn.execute(
        select(s.case_events)
        .where(s.case_events.c.case_id == case_id)
        .order_by(s.case_events.c.seq)
    ).mappings().all()
    return [
        {
            "seq": r["seq"],
            "kind": r["kind"],
            "label": r["label"],
            "payload": json.loads(r["payload_json"]),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# Evidence loaders
# --------------------------------------------------------------------------- #


def load_inventory(conn: Connection, sku: str, node_id: str) -> InventoryPosition | None:
    row = conn.execute(
        select(s.inventory_snapshots).where(
            s.inventory_snapshots.c.sku == sku,
            s.inventory_snapshots.c.node_id == node_id,
        )
    ).mappings().first()
    if row is None:
        return None
    return InventoryPosition(
        sku=row["sku"],
        node_id=row["node_id"],
        on_hand=row["on_hand"],
        reserved=row["reserved"],
        quarantine=row["quarantine"],
        damaged=row["damaged"],
        effective_at=row["effective_at"],
        version=row["version"],
    )


def load_demand(
    conn: Connection, sku: str, node_id: str, start: date, days: int
) -> list[DemandDay]:
    end = start + timedelta(days=days - 1)
    rows = conn.execute(
        select(s.demand_records)
        .where(
            s.demand_records.c.sku == sku,
            s.demand_records.c.node_id == node_id,
            s.demand_records.c.date >= start,
            s.demand_records.c.date <= end,
        )
        .order_by(s.demand_records.c.date)
    ).mappings().all()
    return [
        DemandDay(
            day=r["date"],
            forecast_units=r["forecast_units"],
            actual_sales_units=r["actual_sales_units"],
            in_stock_pct=r["in_stock_pct"],
            promotion_id=r["promotion_id"],
        )
        for r in rows
    ]


def load_sales_history(
    conn: Connection, sku: str, node_id: str, before: date, days: int
) -> list[DemandDay]:
    """Recent *actual* sales, used to test whether a forecast still holds."""
    start = before - timedelta(days=days)
    rows = conn.execute(
        select(s.demand_records)
        .where(
            s.demand_records.c.sku == sku,
            s.demand_records.c.node_id == node_id,
            s.demand_records.c.date >= start,
            s.demand_records.c.date < before,
        )
        .order_by(s.demand_records.c.date)
    ).mappings().all()
    return [
        DemandDay(
            day=r["date"],
            forecast_units=r["forecast_units"],
            actual_sales_units=r["actual_sales_units"],
            in_stock_pct=r["in_stock_pct"],
            promotion_id=r["promotion_id"],
        )
        for r in rows
    ]


def load_promotions(conn: Connection, sku: str) -> list[Promotion]:
    rows = conn.execute(
        select(s.promotions).where(s.promotions.c.sku == sku).order_by(s.promotions.c.start_date)
    ).mappings().all()
    return [
        Promotion(
            promotion_id=r["promotion_id"],
            sku=r["sku"],
            start_date=r["start_date"],
            end_date=r["end_date"],
            uplift_factor=r["uplift_factor"],
            label=r["label"],
        )
        for r in rows
    ]


def load_open_orders(conn: Connection, sku: str, node_id: str) -> list[OpenOrder]:
    """Purchase orders that still owe units. Fully received or cancelled POs are
    excluded so they cannot be double-counted as incoming supply."""
    rows = conn.execute(
        select(s.purchase_orders)
        .where(
            s.purchase_orders.c.sku == sku,
            s.purchase_orders.c.node_id == node_id,
            s.purchase_orders.c.status.notin_(["cancelled", "received"]),
        )
        .order_by(s.purchase_orders.c.requested_date)
    ).mappings().all()
    orders = [
        OpenOrder(
            po_id=r["po_id"],
            sku=r["sku"],
            node_id=r["node_id"],
            supplier_id=r["supplier_id"],
            requested_qty=r["requested_qty"],
            confirmed_qty=r["confirmed_qty"],
            received_qty=r["received_qty"],
            cancelled_qty=r["cancelled_qty"],
            requested_date=r["requested_date"],
            confirmed_date=r["confirmed_date"],
            status=POStatus(r["status"]),
            acknowledged_at=r["acknowledged_at"],
            version=r["version"],
        )
        for r in rows
    ]
    return [o for o in orders if o.outstanding_qty > 0]


def load_quotes(conn: Connection, sku: str) -> list[SupplierQuote]:
    rows = conn.execute(
        select(s.supplier_quotes)
        .where(s.supplier_quotes.c.sku == sku)
        .order_by(s.supplier_quotes.c.unit_price_minor)
    ).mappings().all()
    return [
        SupplierQuote(
            supplier_id=r["supplier_id"],
            sku=r["sku"],
            unit_price_minor=r["unit_price_minor"],
            moq=r["moq"],
            pack_size=r["pack_size"],
            lead_time_days=r["lead_time_days"],
            available_units=r["available_units"],
            quote_expires_at=r["quote_expires_at"],
            eligible=bool(r["eligible"]),
            expedite_available=bool(r["expedite_available"]),
            expedite_fee_minor=r["expedite_fee_minor"],
            expedite_days_saved=r["expedite_days_saved"],
        )
        for r in rows
    ]


def load_budget(conn: Connection, scope: str, period: str) -> Budget | None:
    row = conn.execute(
        select(s.budgets).where(s.budgets.c.scope == scope, s.budgets.c.period == period)
    ).mappings().first()
    if row is None:
        return None
    return Budget(
        scope=row["scope"],
        period=row["period"],
        limit_minor=row["limit_minor"],
        committed_minor=row["committed_minor"],
        reserved_minor=row["reserved_minor"],
        version=row["version"],
    )


def load_capacity(
    conn: Connection, node_id: str, start: date, days: int
) -> list[CapacityDay]:
    end = start + timedelta(days=days - 1)
    rows = conn.execute(
        select(s.capacity_projections)
        .where(
            s.capacity_projections.c.node_id == node_id,
            s.capacity_projections.c.date >= start,
            s.capacity_projections.c.date <= end,
        )
        .order_by(s.capacity_projections.c.date)
    ).mappings().all()
    return [
        CapacityDay(
            day=r["date"],
            capacity_m3=r["capacity_m3"],
            occupied_m3=r["occupied_m3"],
            inbound_m3=r["inbound_m3"],
        )
        for r in rows
    ]


def load_product(conn: Connection, sku: str) -> dict | None:
    row = conn.execute(select(s.products).where(s.products.c.sku == sku)).mappings().first()
    return dict(row) if row else None


def load_case(conn: Connection, case_id: str) -> dict | None:
    row = conn.execute(select(s.cases).where(s.cases.c.case_id == case_id)).mappings().first()
    if row is None:
        return None
    case = dict(row)
    case["trigger_payload"] = json.loads(case["trigger_payload"])
    return case


def set_case_state(conn: Connection, case_id: str, state: str) -> None:
    conn.execute(
        s.cases.update().where(s.cases.c.case_id == case_id).values(state=state)
    )


def touch_po_version(conn: Connection, po_id: str, expected_version: int, **values) -> bool:
    """Update a purchase order only if it still has the version we read.

    Returns False when another writer got there first, which the caller must treat
    as a stale-state condition rather than retrying blindly.
    """
    result = conn.execute(
        s.purchase_orders.update()
        .where(
            s.purchase_orders.c.po_id == po_id,
            s.purchase_orders.c.version == expected_version,
        )
        .values(version=expected_version + 1, **values)
    )
    return result.rowcount == 1


def utcnow() -> datetime:
    return datetime.utcnow()
