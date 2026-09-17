import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from datetime import date, timedelta
from app.domain.candidates import PlanningContext, simulate_all, rank, required_quantity, baseline_projection
from app.domain.types import (Budget, CapacityDay, DemandDay, InventoryPosition,
                               PolicyConfig, SupplierQuote, ActionType)

START = date(2026, 9, 17)
D, X, occ, cap = 17, 176, 186.86, 200.0
demand=[DemandDay(day=START+timedelta(days=i), forecast_units=D) for i in range(28)]
c = PlanningContext(
    sku="SKU-1003", node_id="NODE-BOG", today=START,
    inventory=InventoryPosition("SKU-1003","NODE-BOG",X,0,0,0,START),
    demand=demand, open_orders=[],
    quotes=[SupplierQuote("SUP-A","SKU-1003",1300,250,50,7,5000,START+timedelta(days=20),True)],
    budget=Budget("NODE-BOG","2026-09",5_000_000,0,0),
    capacity=[CapacityDay(day=START+timedelta(days=i), capacity_m3=cap, occupied_m3=occ) for i in range(28)],
    unit_volume_m3=0.02, policy=PolicyConfig(),
)
b = baseline_projection(c)
print("baseline unmet", b.total_unmet_units, "first_stockout", b.first_stockout_date, "closing", b.closing_inventory)
print("required_quantity", required_quantity(c))
ranked = rank(simulate_all(c, recommended_qty=800))
for r in ranked:
    print(r.candidate.action_type, r.candidate.qty, r.feasible, r.binding_constraints, "after_unmet",r.after.total_unmet_units,"closing",r.after.closing_inventory,"cost",r.incremental_cost_minor,"peak",r.after.peak_occupancy_m3)
