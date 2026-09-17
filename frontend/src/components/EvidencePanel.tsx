import { Pill } from './Badges';
import { dateShort, money, num, titleCase } from '../format';
import type { Evidence } from '../types';

export function EvidencePanel({ evidence }: { evidence: Evidence }) {
  const inv = evidence.inventory;
  const capacityUnits = evidence.capacity.unit_volume_m3 > 0
    ? Math.floor(evidence.capacity.min_headroom_m3 / evidence.capacity.unit_volume_m3)
    : null;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {/* Inventory */}
      <Card icon="▦" title="Inventory position" subtitle={`Snapshot ${dateShort(inv.effective_at)}`}>
        <div className="space-y-1 text-sm">
          <Row label="On hand" value={num(inv.on_hand)} />
          <Row label="− Reserved" value={num(inv.reserved)} sub />
          <Row label="− Quarantine" value={num(inv.quarantine)} sub />
          <Row label="− Damaged" value={num(inv.damaged)} sub />
          <div className="my-1 border-t border-gray-800" />
          <Row label="= Usable" value={num(inv.usable)} strong />
          <p className="mt-2 text-xs text-gray-500">
            Snapshot age: {inv.snapshot_age_days} day{inv.snapshot_age_days === 1 ? '' : 's'}
          </p>
        </div>
      </Card>

      <Card icon="⌁" title="Demand and service target" subtitle={`${evidence.demand.horizon_days}-day planning horizon`}>
        <div className="space-y-1 text-sm">
          <Row label="Forecast demand" value={`${num(evidence.demand.forecast_total_units)} units`} />
          <Row label="Average daily demand" value={`${num(evidence.demand.average_daily_units)} units`} />
          <Row label="Safety stock target" value={`${num(evidence.demand.safety_stock_units)} units`} strong />
        </div>
      </Card>

      {/* Budget */}
      <Card icon="$" title="Purchasing budget" subtitle="Current planning period">
        {evidence.budget.limit_minor == null ? (
          <p className="text-sm text-gray-500">No budget on record for this scope.</p>
        ) : (
          <div className="space-y-1 text-sm">
            <Row label="Limit" value={money(evidence.budget.limit_minor)} />
            <Row label="Committed" value={money(evidence.budget.committed_minor)} sub />
            <Row label="Reserved" value={money(evidence.budget.reserved_minor)} sub />
            <div className="my-1 border-t border-gray-800" />
            <Row label="Available" value={money(evidence.budget.available_minor)} strong />
          </div>
        )}
      </Card>

      {/* Open orders */}
      <Card icon="⇢" title="Open purchase orders" subtitle="Confirmed inbound supply" span>
        {evidence.open_orders.length === 0 ? (
          <p className="text-sm text-gray-500">No open purchase orders.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="py-1 pr-3 font-medium">PO</th>
                  <th className="py-1 pr-3 font-medium">Supplier</th>
                  <th className="py-1 pr-3 font-medium">Outstanding</th>
                  <th className="py-1 pr-3 font-medium">Requested / confirmed</th>
                  <th className="py-1 pr-3 font-medium">Confirmed date</th>
                  <th className="py-1 pr-3 font-medium">Status</th>
                  <th className="py-1 pr-3 font-medium">Flags</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {evidence.open_orders.map((o) => (
                  <tr key={o.po_id} className={o.overdue ? 'bg-red-950/20' : !o.acknowledged ? 'bg-amber-950/20' : ''}>
                    <td className="py-1.5 pr-3 font-mono text-xs">{o.po_id}</td>
                    <td className="py-1.5 pr-3">{o.supplier_id}</td>
                    <td className="py-1.5 pr-3">{num(o.outstanding_qty)}</td>
                    <td className="py-1.5 pr-3">{num(o.requested_qty)} / {num(o.confirmed_qty)}</td>
                    <td className="py-1.5 pr-3">{dateShort(o.confirmed_date)}</td>
                    <td className="py-1.5 pr-3">{titleCase(o.status)}</td>
                    <td className="py-1.5 pr-3 space-x-1">
                      {o.overdue && <Pill tone="bad">Overdue</Pill>}
                      {!o.acknowledged && <Pill tone="warn">Unacknowledged</Pill>}
                      {!o.overdue && o.acknowledged && <Pill tone="good">OK</Pill>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Capacity */}
      <Card icon="▣" title="Storage capacity" subtitle="Tightest point in the horizon">
        <div className="space-y-1 text-sm">
          <Row label="Min headroom (horizon)" value={`${evidence.capacity.min_headroom_m3} m³`} />
          <Row label="Unit volume" value={`${evidence.capacity.unit_volume_m3} m³`} />
          <Row label="Approx. unit headroom" value={capacityUnits == null ? '—' : `${num(capacityUnits)} units`} strong />
        </div>
      </Card>

      <Card icon="♙" title="Supplier options" subtitle="Live commercial constraints" span>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="py-1 pr-3 font-medium">Supplier</th>
                <th className="py-1 pr-3 font-medium">Unit price</th>
                <th className="py-1 pr-3 font-medium">MOQ / pack</th>
                <th className="py-1 pr-3 font-medium">Lead time</th>
                <th className="py-1 pr-3 font-medium">Available</th>
                <th className="py-1 pr-3 font-medium">Quote expiry</th>
                <th className="py-1 pr-3 font-medium">Expedite</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {evidence.suppliers.map((supplier) => (
                <tr key={supplier.supplier_id} className={!supplier.eligible ? 'opacity-50' : ''}>
                  <td className="py-2 pr-3 font-medium text-gray-200">{supplier.supplier_id} {!supplier.eligible && <Pill tone="bad">Ineligible</Pill>}</td>
                  <td className="py-2 pr-3">{money(supplier.unit_price_minor)}</td>
                  <td className="py-2 pr-3">{num(supplier.moq)} / {num(supplier.pack_size)}</td>
                  <td className="py-2 pr-3">{supplier.lead_time_days} days</td>
                  <td className="py-2 pr-3">{num(supplier.available_units)}</td>
                  <td className="py-2 pr-3">{dateShort(supplier.quote_expires_at)}</td>
                  <td className="py-2 pr-3">{supplier.expedite_available ? `${supplier.expedite_days_saved} days · ${money(supplier.expedite_fee_minor)}` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Unknowns */}
      <Card icon="?" title="Evidence completeness" tone={evidence.unknowns.length ? 'warn' : undefined}>
        {evidence.unknowns.length === 0 ? (
          <p className="text-sm text-gray-500">No unresolved evidence gaps.</p>
        ) : (
          <ul className="list-disc space-y-1 pl-4 text-sm text-amber-300">
            {evidence.unknowns.map((u, i) => (
              <li key={i}>{u}</li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Card({
  title,
  icon,
  subtitle,
  children,
  span,
  tone,
}: {
  title: string;
  icon?: string;
  subtitle?: string;
  children: React.ReactNode;
  span?: boolean;
  tone?: 'warn';
}) {
  return (
    <div
      className={`rounded-lg border p-4 ${span ? 'lg:col-span-2' : ''} ${
        tone === 'warn' ? 'border-amber-800/60 bg-amber-950/10' : 'border-gray-800 bg-gray-950'
      }`}
    >
      <div className="mb-3 flex items-start gap-2">
        {icon && <span className="flex h-7 w-7 items-center justify-center rounded-md border border-gray-700 bg-gray-900 text-xs text-sky-300" aria-hidden>{icon}</span>}
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-300">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-gray-600">{subtitle}</p>}
        </div>
      </div>
      {children}
    </div>
  );
}

function Row({ label, value, sub, strong }: { label: string; value: string; sub?: boolean; strong?: boolean }) {
  return (
    <div className={`flex items-center justify-between ${sub ? 'text-gray-500' : 'text-gray-200'}`}>
      <span className={strong ? 'font-semibold text-gray-100' : ''}>{label}</span>
      <span className={`font-mono ${strong ? 'font-semibold text-gray-100' : ''}`}>{value}</span>
    </div>
  );
}
