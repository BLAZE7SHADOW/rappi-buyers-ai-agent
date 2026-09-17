import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from datetime import date, timedelta
from app.domain.candidates import PlanningContext, simulate_all, rank, required_quantity, baseline_projection
from app.domain.types import (Budget, CapacityDay, DemandDay, InventoryPosition, OpenOrder, POStatus,
                               PolicyConfig, SupplierQuote, ActionType)

START = date(2026, 9, 17)

def mkctx(**over):
    base = dict(
        sku="SKU-1001", node_id="NODE-BOG", today=START,
        inventory=InventoryPosition("SKU-1001","NODE-BOG",1200,150,50,0,START),
        demand=[DemandDay(day=START+timedelta(days=i), forecast_units=100) for i in range(28)],
        open_orders=[OpenOrder("PO-501","SKU-1001","NODE-BOG","SUP-A",2000,2000,0,0,
                                START+timedelta(days=14), START+timedelta(days=14),
                                POStatus.CONFIRMED, acknowledged_at=START)],
        quotes=[SupplierQuote("SUP-A","SKU-1001",1500,500,50,7,5000,START+timedelta(days=20),True,
                              expedite_available=True, expedite_fee_minor=45000, expedite_days_saved=4),
                SupplierQuote("SUP-B","SKU-1001",1750,250,50,3,3000,START+timedelta(days=20),True)],
        budget=Budget("NODE-BOG","2026-09",900_000,0,0),
        capacity=[CapacityDay(day=START+timedelta(days=i), capacity_m3=200.0, occupied_m3=20.0) for i in range(28)],
        unit_volume_m3=0.02, policy=PolicyConfig(),
    )
    base.update(over)
    return PlanningContext(**base)

c = mkctx()
b = baseline_projection(c)
print("baseline unmet", b.total_unmet_units, "first stockout", b.first_stockout_date)
ranked = rank(simulate_all(c, recommended_qty=800))
for r in ranked[:6]:
    print(r.candidate.action_type, r.candidate.qty, r.candidate.po_id, r.feasible, r.binding_constraints, r.after.total_unmet_units, r.incremental_cost_minor)

print("\n--- F2 ---")
c2 = PlanningContext(
    sku="SKU-1002", node_id="NODE-BOG", today=START,
    inventory=InventoryPosition("SKU-1002","NODE-BOG", on_hand=380+150, reserved=150, quarantine=0, damaged=0, effective_at=START),
    demand=[DemandDay(day=START+timedelta(days=i), forecast_units=35) for i in range(28)],
    open_orders=[],
    quotes=[SupplierQuote("SUP-A","SKU-1002",1200,500,100,7,5000,START+timedelta(days=20),True)],
    budget=Budget("NODE-BOG","2026-09",2_000_000,0,0),
    capacity=[CapacityDay(day=START+timedelta(days=i), capacity_m3=200.0, occupied_m3=20.0) for i in range(28)],
    unit_volume_m3=0.02, policy=PolicyConfig(),
)
print("usable", c2.inventory.usable)
b2 = baseline_projection(c2)
print("baseline unmet", b2.total_unmet_units, "closing", b2.closing_inventory)
print("required_quantity", required_quantity(c2))
ranked2 = rank(simulate_all(c2, recommended_qty=800))
for r in ranked2[:5]:
    print(r.candidate.action_type, r.candidate.qty, r.feasible, r.binding_constraints, r.after.total_unmet_units, r.incremental_cost_minor)
