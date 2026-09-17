"""Database schema, declared with SQLAlchemy Core.

Core rather than the ORM: queries stay SQL-shaped and explicit, transactions are
obvious, and there is no lazy-loading behaviour hiding inside the executor.

Using SQLAlchemy also keeps the dialect portable. The default is SQLite so the app
runs with no infrastructure, but pointing ``DATABASE_URL`` at Postgres/Supabase
requires no code changes -- the optimistic-version-check concurrency design is
already dialect-agnostic.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)

metadata = MetaData()

products = Table(
    "products", metadata,
    Column("sku", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("unit_volume_m3", Float, nullable=False, default=0.01),
    Column("status", String, nullable=False, default="active"),
)

nodes = Table(
    "nodes", metadata,
    Column("node_id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("timezone", String, nullable=False, default="America/Bogota"),
    Column("capacity_m3", Float, nullable=False),
)

inventory_snapshots = Table(
    "inventory_snapshots", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sku", String, nullable=False),
    Column("node_id", String, nullable=False),
    Column("on_hand", Integer, nullable=False),
    Column("reserved", Integer, nullable=False, default=0),
    Column("quarantine", Integer, nullable=False, default=0),
    Column("damaged", Integer, nullable=False, default=0),
    Column("effective_at", Date, nullable=False),
    Column("version", Integer, nullable=False, default=1),
    UniqueConstraint("sku", "node_id", name="uq_inventory_sku_node"),
)

demand_records = Table(
    "demand_records", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sku", String, nullable=False),
    Column("node_id", String, nullable=False),
    Column("date", Date, nullable=False),
    Column("forecast_units", Integer, nullable=False, default=0),
    # NULL actual sales means "no evidence", which is not the same as zero sales.
    Column("actual_sales_units", Integer, nullable=True),
    # 0.0 availability with 0 sales marks the day as stockout-censored evidence.
    Column("in_stock_pct", Float, nullable=True),
    Column("promotion_id", String, nullable=True),
    UniqueConstraint("sku", "node_id", "date", name="uq_demand_sku_node_date"),
)

promotions = Table(
    "promotions", metadata,
    Column("promotion_id", String, primary_key=True),
    Column("sku", String, nullable=False),
    Column("start_date", Date, nullable=False),
    Column("end_date", Date, nullable=False),
    Column("uplift_factor", Float, nullable=False, default=1.0),
    Column("label", String, nullable=False, default=""),
)

suppliers = Table(
    "suppliers", metadata,
    Column("supplier_id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("reliability_score", Float, nullable=False, default=1.0),
)

supplier_quotes = Table(
    "supplier_quotes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("supplier_id", String, nullable=False),
    Column("sku", String, nullable=False),
    Column("unit_price_minor", Integer, nullable=False),
    Column("moq", Integer, nullable=False, default=0),
    Column("pack_size", Integer, nullable=False, default=1),
    Column("lead_time_days", Integer, nullable=False),
    Column("available_units", Integer, nullable=False),
    Column("quote_expires_at", Date, nullable=False),
    Column("eligible", Boolean, nullable=False, default=True),
    Column("expedite_available", Boolean, nullable=False, default=False),
    Column("expedite_fee_minor", Integer, nullable=False, default=0),
    Column("expedite_days_saved", Integer, nullable=False, default=0),
    UniqueConstraint("supplier_id", "sku", name="uq_quote_supplier_sku"),
)

purchase_orders = Table(
    "purchase_orders", metadata,
    Column("po_id", String, primary_key=True),
    Column("sku", String, nullable=False),
    Column("node_id", String, nullable=False),
    Column("supplier_id", String, nullable=False),
    Column("requested_qty", Integer, nullable=False),
    Column("confirmed_qty", Integer, nullable=False, default=0),
    Column("received_qty", Integer, nullable=False, default=0),
    Column("cancelled_qty", Integer, nullable=False, default=0),
    Column("unit_price_minor", Integer, nullable=False, default=0),
    Column("fee_minor", Integer, nullable=False, default=0),
    Column("requested_date", Date, nullable=False),
    Column("confirmed_date", Date, nullable=True),
    Column("status", String, nullable=False, default="draft"),
    Column("acknowledged_at", Date, nullable=True),
    Column("created_by_case", String, nullable=True),
    # Optimistic concurrency: writers assert the version they read.
    Column("version", Integer, nullable=False, default=1),
)

budgets = Table(
    "budgets", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("scope", String, nullable=False),
    Column("period", String, nullable=False),
    Column("limit_minor", Integer, nullable=False),
    Column("committed_minor", Integer, nullable=False, default=0),
    Column("reserved_minor", Integer, nullable=False, default=0),
    Column("version", Integer, nullable=False, default=1),
    UniqueConstraint("scope", "period", name="uq_budget_scope_period"),
)

capacity_projections = Table(
    "capacity_projections", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("node_id", String, nullable=False),
    Column("date", Date, nullable=False),
    Column("capacity_m3", Float, nullable=False),
    Column("occupied_m3", Float, nullable=False, default=0.0),
    Column("inbound_m3", Float, nullable=False, default=0.0),
    Column("version", Integer, nullable=False, default=1),
    UniqueConstraint("node_id", "date", name="uq_capacity_node_date"),
)

cases = Table(
    "cases", metadata,
    Column("case_id", String, primary_key=True),
    Column("fixture_id", String, nullable=True),
    Column("sku", String, nullable=False),
    Column("node_id", String, nullable=False),
    Column("trigger_type", String, nullable=False),
    Column("trigger_payload", Text, nullable=False, default="{}"),
    Column("title", String, nullable=False, default=""),
    Column("state", String, nullable=False, default="investigating"),
    Column("replan_count", Integer, nullable=False, default=0),
    Column("as_of_date", Date, nullable=False),
    # Which mock-supplier behaviour this case's next action will encounter.
    Column("supplier_behavior", String, nullable=False, default="confirm_full"),
    Column("created_at", DateTime, server_default=func.now()),
)

# Append-only. Powers the UI timeline, the audit trail, and the eval assertions.
# Never UPDATE a row here; only INSERT.
case_events = Table(
    "case_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", String, nullable=False),
    Column("seq", Integer, nullable=False),
    Column("kind", String, nullable=False),
    Column("label", String, nullable=False, default=""),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("created_at", DateTime, server_default=func.now()),
    UniqueConstraint("case_id", "seq", name="uq_event_case_seq"),
)

proposals = Table(
    "proposals", metadata,
    Column("proposal_id", String, primary_key=True),
    Column("case_id", String, nullable=False),
    Column("version", Integer, nullable=False, default=1),
    Column("disposition", String, nullable=False),
    Column("action_type", String, nullable=False),
    Column("action_args_json", Text, nullable=False, default="{}"),
    Column("evidence_refs_json", Text, nullable=False, default="[]"),
    Column("simulation_json", Text, nullable=False, default="{}"),
    Column("rationale", Text, nullable=False, default=""),
    Column("important_factors_json", Text, nullable=False, default="[]"),
    Column("assumptions_json", Text, nullable=False, default="[]"),
    Column("residual_exposure_json", Text, nullable=False, default="{}"),
    # Computed by the server gate, never by the model.
    Column("approval_required", Boolean, nullable=False, default=True),
    Column("approval_reason", String, nullable=False, default=""),
    Column("state", String, nullable=False, default="proposed"),
    Column("decided_by", String, nullable=True),
    Column("decided_at", DateTime, nullable=True),
    Column("decline_reason", Text, nullable=True),
    Column("created_at", DateTime, server_default=func.now()),
)

interactions = Table(
    "interactions", metadata,
    Column("interaction_id", String, primary_key=True),
    Column("case_id", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("question", Text, nullable=False),
    Column("context_json", Text, nullable=False, default="{}"),
    Column("options_json", Text, nullable=False, default="[]"),
    Column("recommendation", Text, nullable=False, default=""),
    Column("answer", Text, nullable=True),
    Column("answered_at", DateTime, nullable=True),
    Column("created_at", DateTime, server_default=func.now()),
)

actions = Table(
    "actions", metadata,
    Column("action_id", String, primary_key=True),
    Column("case_id", String, nullable=False),
    Column("proposal_id", String, nullable=False),
    Column("proposal_version", Integer, nullable=False, default=1),
    Column("action_type", String, nullable=False),
    # The duplicate-suppression mechanism: one intended action has one key across
    # every retry, and the UNIQUE constraint is what makes that enforceable.
    Column("idempotency_key", String, nullable=False, unique=True),
    Column("request_json", Text, nullable=False, default="{}"),
    Column("response_json", Text, nullable=True),
    Column("po_id", String, nullable=True),
    Column("state", String, nullable=False, default="pending"),
    Column("verdict_json", Text, nullable=True),
    Column("attempts", Integer, nullable=False, default=0),
    Column("created_at", DateTime, server_default=func.now()),
)

# Deduplicated inbound supplier messages; out-of-order/stale ones are rejected.
supplier_events = Table(
    "supplier_events", metadata,
    Column("event_id", String, primary_key=True),
    Column("po_id", String, nullable=False),
    Column("case_id", String, nullable=True),
    Column("kind", String, nullable=False),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("sequence", Integer, nullable=False, default=0),
    Column("processed", Boolean, nullable=False, default=False),
    Column("created_at", DateTime, server_default=func.now()),
)

agent_runs = Table(
    "agent_runs", metadata,
    Column("run_id", String, primary_key=True),
    Column("case_id", String, nullable=False),
    Column("mode", String, nullable=False, default="live"),
    Column("provider", String, nullable=False, default=""),
    Column("model", String, nullable=False, default=""),
    Column("status", String, nullable=False, default="running"),
    Column("tool_call_count", Integer, nullable=False, default=0),
    Column("error", Text, nullable=True),
    Column("started_at", DateTime, server_default=func.now()),
    Column("finished_at", DateTime, nullable=True),
)

ALL_TABLES = list(metadata.tables.keys())
