"""Provider-agnostic tool declarations.

Plain JSON Schema, translated per provider by the adapters. Keeping the canonical
definition here means swapping Gemini for Anthropic is an adapter change, not a
rewrite of the tool surface.
"""

from __future__ import annotations

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "get_case_context",
        "description": (
            "Start here. Returns the trigger under review, the product and node, "
            "purchasing policy, autonomy limits, any prior proposals, buyer answers, "
            "and a list of known unknowns."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_inventory",
        "description": (
            "Current stock broken into on-hand, reserved, quarantined and damaged, "
            "plus the usable figure that can actually serve demand, and how old the "
            "snapshot is."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_demand_evidence",
        "description": (
            "Forecast for the horizon plus recent actual sales, per-day stock "
            "availability, and any promotions. Use this before changing a demand "
            "assumption: it flags stockout-censored days and promotion windows."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "lookback_days": {
                    "type": "integer",
                    "description": "How many days of sales history to return (default 14).",
                }
            },
        },
    },
    {
        "name": "get_open_orders",
        "description": (
            "Purchase orders that still owe units: outstanding quantity, status, "
            "confirmed date, whether the supplier has acknowledged, and whether the "
            "order is overdue."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_supplier_options",
        "description": (
            "Eligible supplier quotes with price, MOQ, pack size, lead time, "
            "availability and expiry, plus which existing orders can be expedited "
            "and at what fee."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_constraints",
        "description": (
            "Available budget, dated storage headroom, and the autonomy limits above "
            "which buyer approval is required."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "simulate_plan",
        "description": (
            "The only source of numbers. Call with no arguments to score every "
            "candidate plan, or with an action_type to evaluate one specific plan. "
            "Returns the day-by-day projection before and after, feasibility, and "
            "the binding constraint for anything infeasible. Never state a quantity, "
            "cost, date or shortage that did not come from this tool."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "enum": ["keep_plan", "create_po", "expedite_po"],
                    "description": "Omit to compare all candidates.",
                },
                "supplier_id": {"type": "string"},
                "qty": {"type": "integer"},
                "expected_receipt_date": {"type": "string", "description": "YYYY-MM-DD"},
                "po_id": {"type": "string", "description": "For expedite_po."},
                "new_date": {"type": "string", "description": "For expedite_po. YYYY-MM-DD"},
            },
        },
    },
    {
        "name": "propose_plan",
        "description": (
            "Record your decision. The server decides whether it needs buyer "
            "approval and returns that verdict. Separate the disposition (your "
            "judgement on the incoming recommendation) from the action (what should "
            "actually happen): rejecting a proposed order can still mean expediting "
            "an existing one."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "disposition": {
                    "type": "string",
                    "enum": ["accept", "modify", "reject", "investigate", "escalate"],
                    "description": "Your judgement on the recommendation under review.",
                },
                "action_type": {
                    "type": "string",
                    "enum": ["keep_plan", "create_po", "expedite_po", "none"],
                },
                "action_args": {
                    "type": "object",
                    "description": (
                        "For create_po: supplier_id, qty, expected_receipt_date. "
                        "For expedite_po: po_id, new_date. Quantity and price for an "
                        "expedite are taken from the existing order, not from you."
                    ),
                    "properties": {
                        "supplier_id": {"type": "string"},
                        "qty": {"type": "integer"},
                        "expected_receipt_date": {"type": "string"},
                        "po_id": {"type": "string"},
                        "new_date": {"type": "string"},
                    },
                },
                "rationale": {
                    "type": "string",
                    "description": "Why this is the right action, citing the evidence you used.",
                },
                "important_factors": {
                    "type": "array", "items": {"type": "string"},
                    "description": "The factors that actually drove the decision.",
                },
                "assumptions": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Anything you assumed rather than verified.",
                },
                "evidence_refs": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Tools or records this decision rests on.",
                },
            },
            "required": ["disposition", "action_type", "rationale"],
        },
    },
    {
        "name": "ask_buyer",
        "description": (
            "Ask the buyer for business context or a judgement call, and pause. Use "
            "only for what tools cannot answer. Do not ask the buyer to look up "
            "something you can retrieve yourself."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["clarification", "tradeoff"]},
                "question": {"type": "string"},
                "context": {
                    "type": "object",
                    "description": "What you already know and why the answer matters.",
                },
                "options": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Concrete choices with their consequences.",
                },
                "recommendation": {"type": "string"},
            },
            "required": ["question"],
        },
    },
]

# Evidence gathering is selected by the model at runtime. Requiring a concise
# business question makes that choice auditable without exposing chain-of-thought.
REASONED_TOOLS = {
    "get_inventory", "get_demand_evidence", "get_open_orders",
    "get_supplier_options", "get_constraints", "simulate_plan",
}
for _tool in TOOL_SCHEMAS:
    if _tool["name"] in REASONED_TOOLS:
        _tool["parameters"]["properties"]["reason"] = {
            "type": "string",
            "description": (
                "One short buyer-facing sentence explaining the business question "
                "this specific call will answer."
            ),
        }
        _tool["parameters"].setdefault("required", []).append("reason")


def schema_for(name: str) -> dict:
    return next(t for t in TOOL_SCHEMAS if t["name"] == name)
