import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from datetime import date, timedelta
from app.domain.candidates import PlanningContext, simulate_all, required_quantity, round_to_pack
from app.domain.types import (Budget, CapacityDay, DemandDay, InventoryPosition,
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

for D in range(8, 30):
    for X in range(0, 7*D+1, 5):
        c = mk(X, D, 188.0, 200.0)
        rq = required_quantity(c)
        q = c.quote_for("SUP-A")
        rounded = round_to_pack(rq, q)
        if 450 <= rounded <= 600:
            print(f"D={D} X={X} rq={rq} rounded={rounded}")
