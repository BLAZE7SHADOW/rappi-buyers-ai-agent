import { useMemo, useState } from 'react';
import { api } from '../api/client';
import { money, num } from '../format';
import type { CaseOption } from '../types';

export function CreateCaseDialog({
  options,
  onClose,
  onCreated,
}: {
  options: CaseOption[];
  onClose: () => void;
  onCreated: (caseId: string) => void;
}) {
  const [selection, setSelection] = useState(options[0] ? `${options[0].sku}|${options[0].node_id}` : '');
  const [quantity, setQuantity] = useState('800');
  const [reason, setReason] = useState('Reorder recommendation requires buyer review');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const selected = useMemo(() => options.find((o) => `${o.sku}|${o.node_id}` === selection), [options, selection]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    setSaving(true);
    setError('');
    try {
      const result = await api.createCase({
        sku: selected.sku,
        node_id: selected.node_id,
        recommended_qty: Number(quantity),
        reason: reason.trim(),
      });
      onCreated(result.case_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the case.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4" role="presentation" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-case-title"
        className="w-full max-w-xl rounded-2xl border border-gray-700 bg-gray-950 p-6 shadow-2xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-sky-400">Buyer intake</p>
            <h2 id="create-case-title" className="mt-1 text-xl font-semibold text-white">Open a purchasing case</h2>
            <p className="mt-2 text-sm text-gray-400">
              Enter the incoming recommendation. The agent will retrieve the operational constraints and decide whether to accept, modify, reject, or investigate it.
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" className="text-xl text-gray-500 hover:text-white">×</button>
        </div>

        <form onSubmit={submit} className="mt-6 space-y-4">
          <label className="block text-sm text-gray-300">
            Product and fulfillment node
            <select value={selection} onChange={(e) => setSelection(e.target.value)} className="mt-1.5 w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2.5 text-gray-100">
              {options.map((option) => (
                <option key={`${option.sku}|${option.node_id}`} value={`${option.sku}|${option.node_id}`}>
                  {option.product_name} · {option.sku} · {option.node_name}
                </option>
              ))}
            </select>
          </label>

          {selected && (
            <div className="rounded-xl border border-gray-800 bg-gray-900/70 p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">System evidence preview</p>
                  <p className="mt-1 text-sm text-gray-300">Constraints the agent will investigate</p>
                </div>
                <span className={`rounded-full px-2 py-1 text-xs font-medium ${selected.projected_unmet_units > 0 ? 'bg-amber-950 text-amber-300' : 'bg-emerald-950 text-emerald-300'}`}>
                  {selected.projected_unmet_units > 0 ? `${num(selected.projected_unmet_units)} units exposed` : 'No baseline shortage'}
                </span>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                <Preview label="Usable inventory" value={`${num(selected.usable_inventory)} units`} />
                <Preview label="28-day forecast" value={`${num(selected.forecast_units)} units`} />
                <Preview label="Budget available" value={selected.available_budget_minor == null ? 'Unknown' : money(selected.available_budget_minor)} />
                <Preview label="Storage headroom" value={`${num(selected.storage_headroom_m3)} m³`} />
                <Preview label="Eligible suppliers" value={num(selected.eligible_suppliers)} />
                <Preview label="Snapshot" value={selected.as_of_date} />
              </div>
            </div>
          )}

          <label className="block text-sm text-gray-300">
            Recommended purchase quantity
            <input type="number" min="1" required value={quantity} onChange={(e) => setQuantity(e.target.value)} className="mt-1.5 w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2.5 text-gray-100" />
          </label>

          <label className="block text-sm text-gray-300">
            Why was this case raised?
            <textarea required rows={3} value={reason} onChange={(e) => setReason(e.target.value)} className="mt-1.5 w-full resize-none rounded-lg border border-gray-700 bg-gray-900 px-3 py-2.5 text-gray-100" />
          </label>

          <div className="rounded-lg border border-violet-900/60 bg-violet-950/20 p-3 text-xs leading-5 text-violet-200">
            Budget, capacity, demand, supplier terms, MOQ, pack size, lead time, inventory, and open POs are loaded from system records. A buyer cannot override these facts in this form.
          </div>
          {error && <p role="alert" className="text-sm text-red-300">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="rounded-lg border border-gray-700 px-4 py-2 text-sm text-gray-300 hover:bg-gray-900">Cancel</button>
            <button disabled={saving || !selected} className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-50">
              {saving ? 'Creating case…' : 'Create and investigate'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function Preview({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-gray-950 px-3 py-2">
      <p className="text-[11px] text-gray-500">{label}</p>
      <p className="mt-0.5 text-sm font-medium text-gray-200">{value}</p>
    </div>
  );
}
