import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from datetime import date, timedelta
from app.domain.candidates import PlanningContext, simulate_all, required_quantity, round_to_pack, baseline_projection
from app.domain.types import (Budget, CapacityDay, DemandDay, InventoryPosition,
                               PolicyConfig, SupplierQuote, ActionType)

START = date(2026, 9, 17)

def mk(usable, demand_per_day, occ, cap, moq=250, pack=50):
    demand=[DemandDay(day=START+timedelta(days=i), forecast_units=demand_per_day) for i in range(28)]
    return PlanningContext(
        sku="SKU-1003", node_id="NODE-BOG", today=START,
        inventory=InventoryPosition("SKU-1003","NODE-BOG",usable,0,0,0,START),
        demand=demand, open_orders=[],
        quotes=[SupplierQuote("SUP-A","SKU-1003",1300,moq,pack,7,5000,START+timedelta(days=20),True)],
        budget=Budget("NODE-BOG","2026-09",5_000_000,0,0),
        capacity=[CapacityDay(day=START+timedelta(days=i), capacity_m3=cap, occupied_m3=occ) for i in range(28)],
        unit_volume_m3=0.02, policy=PolicyConfig(),
    )

for D in range(16, 26):
    for X in range(0, 400, 2):
        c0 = mk(X, D, 0, 100000)
        rq = required_quantity(c0)
        q = c0.quote_for("SUP-A")
        need_qty = round_to_pack(rq, q)
        if need_qty == 500:
            b = baseline_projection(c0)
            row7 = next(r for r in b.days if r.day==START+timedelta(days=7))
            opening7 = row7.opening
            cap=200.0
            occ = cap - (opening7+600)*0.02
            c = mk(X, D, occ, cap)
            ranked = simulate_all(c, recommended_qty=800)
            r500 = next(r for r in ranked if r.candidate.action_type==ActionType.CREATE_PO and r.candidate.qty==500)
            r800 = next(r for r in ranked if r.candidate.action_type==ActionType.CREATE_PO and r.candidate.qty==800)
            if r500.feasible and not r800.feasible:
                print(f"D={D} X={X} opening7={opening7} occ={occ:.2f} closing500={r500.after.closing_inventory} r800_bind={r800.binding_constraints}")
