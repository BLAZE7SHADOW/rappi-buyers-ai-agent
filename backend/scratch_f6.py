import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from datetime import date, timedelta
from app.domain.candidates import PlanningContext, simulate_all, rank, required_quantity, baseline_projection, best
from app.domain.types import (Budget, CapacityDay, DemandDay, InventoryPosition,
                               PolicyConfig, SupplierQuote, ActionType)

START = date(2026, 9, 17)
demand=[DemandDay(day=START+timedelta(days=i), forecast_units=50) for i in range(28)]
c = PlanningContext(
    sku="SKU-1006", node_id="NODE-BOG", today=START,
    inventory=InventoryPosition("SKU-1006","NODE-BOG",800,0,0,0,START),
    demand=demand, open_orders=[],
    quotes=[SupplierQuote("SUP-A","SKU-1006",1000,100,50,7,2000,START+timedelta(days=20),True)],
    budget=Budget("NODE-BOG","2026-09",0,0,0),
    capacity=[CapacityDay(day=START+timedelta(days=i), capacity_m3=200.0, occupied_m3=20.0) for i in range(28)],
    unit_volume_m3=0.02, policy=PolicyConfig(),
)
b = baseline_projection(c)
print("baseline unmet", b.total_unmet_units)
ranked = rank(simulate_all(c, recommended_qty=600))
for r in ranked:
    print(r.candidate.action_type, r.candidate.qty, r.feasible, r.binding_constraints, r.after.total_unmet_units)
print("best:", best(simulate_all(c, recommended_qty=600)))
