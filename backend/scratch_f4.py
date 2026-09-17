import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from datetime import date, timedelta
from app.domain.demand import analyze, promotion_bounded_demand, sustained_demand
from app.domain.types import DemandDay, Promotion, PolicyConfig

START = date(2026, 9, 17)

history = []
for i in range(-14, 0):
    day = START + timedelta(days=i)
    if i in (-11, -10, -9):
        history.append(DemandDay(day=day, forecast_units=50, actual_sales_units=0, in_stock_pct=0.0))
    else:
        history.append(DemandDay(day=day, forecast_units=50, actual_sales_units=130, in_stock_pct=1.0))

forecast = [DemandDay(day=START+timedelta(days=i), forecast_units=50) for i in range(28)]
promo = Promotion("PROMO-1", "SKU-1004", START+timedelta(days=-10), START+timedelta(days=6), 2.6, "Spike promo")

res = analyze(history=history, forecast=forecast, promotions=[promo], today=START)
import json
print(json.dumps(res, indent=2))

pb = promotion_bounded_demand(forecast=forecast, promotions=[promo], observed_daily=res["observed_daily_sales_excluding_censored"], today=START)
print("promo-bounded total:", sum(pb.values()))
sd = sustained_demand(forecast=forecast, observed_daily=res["observed_daily_sales_excluding_censored"])
print("sustained total:", sum(sd.values()))
