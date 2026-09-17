import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from datetime import date, timedelta
from app.domain.candidates import PlanningContext, simulate_all, rank, required_quantity, baseline_projection
from app.domain.types import (Budget, CapacityDay, DemandDay, InventoryPosition, OpenOrder, POStatus,
                               PolicyConfig, SupplierQuote, ActionType)

START = date(2026, 9, 17)

def mk(usable, demand_per_day, occ, cap, moq=250, pack=50):
    demand=[DemandDay(day=START+timedelta(days=i), forecast_units=demand_per_day) for i in range(28)]
    return PlanningContext(
        sku="SKU-1003", node_id="NODE-BOG", today=START,
        inventory=InventoryPosition("SKU-1003","NODE-BOG",usable,0,0,0,START),
        demand=demand,
        open_orders=[],
        quotes=[SupplierQuote("SUP-A","SKU-1003",1300,moq,pack,7,5000,START+timedelta(days=20),True)],
        budget=Budget("NODE-BOG","2026-09",5_000_000,0,0),
        capacity=[CapacityDay(day=START+timedelta(days=i), capacity_m3=cap, occupied_m3=occ) for i in range(28)],
        unit_volume_m3=0.02, policy=PolicyConfig(),
    )

for usable, dpd, occ, cap in [
    (300, 40, 188.0, 200.0),
    (250, 40, 188.0, 200.0),
    (200, 40, 188.0, 200.0),
]:
    c = mk(usable, dpd, occ, cap)
    b = baseline_projection(c)
    print(f"usable={usable} dpd={dpd} -> baseline unmet={b.total_unmet_units} required_quantity={required_quantity(c)}")
    ranked = rank(simulate_all(c, recommended_qty=800))
    for r in ranked:
        print("  ", r.candidate.action_type, r.candidate.qty, r.feasible, r.binding_constraints, r.after.total_unmet_units, r.after.closing_inventory, r.incremental_cost_minor)

print("\n--- targeted ---")
c = mk(usable=92, demand_per_day=14, occ=188.0, cap=200.0, moq=250, pack=50)
b = baseline_projection(c)
print(f"baseline unmet={b.total_unmet_units} first_stockout={b.first_stockout_date} required_quantity={required_quantity(c)}")
ranked = rank(simulate_all(c, recommended_qty=800))
for r in ranked:
    print("  ", r.candidate.action_type, r.candidate.qty, r.feasible, r.binding_constraints, r.after.total_unmet_units, r.after.closing_inventory, r.incremental_cost_minor)
