import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { StateBadge, VerdictBadge } from '../components/Badges';
import { CreateCaseDialog } from '../components/CreateCaseDialog';
import { EmptyState, ErrorBanner, Spinner } from '../components/StatusViews';
import { dateShort, dateTimeShort, num, titleCase } from '../format';
import type { CaseListItem, CaseOption } from '../types';

export function Inbox() {
  const navigate = useNavigate();
  const [cases, setCases] = useState<CaseListItem[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'agent' | 'buyer' | 'closed'>('all');
  const [showCreate, setShowCreate] = useState(false);
  const [caseOptions, setCaseOptions] = useState<CaseOption[]>([]);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .listCases()
      .then((res) => setCases(res.cases))
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    api
      .listCases()
      .then((res) => setCases(res.cases))
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
    api.caseOptions().then((res) => setCaseOptions(res.options)).catch(() => setCaseOptions([]));
  }, []);

  const counts = cases?.reduce((acc, item) => {
    if (['investigating', 'pending_investigation', 'reopened'].includes(item.state)) acc.agent += 1;
    if (['awaiting_buyer', 'awaiting_approval'].includes(item.state)) acc.buyer += 1;
    if (item.state === 'resolved') acc.resolved += 1;
    if (item.state === 'escalated') acc.escalated += 1;
    return acc;
  }, { agent: 0, buyer: 0, resolved: 0, escalated: 0 });
  const visibleCases = cases?.filter((item) => {
    if (filter === 'agent') return ['investigating', 'pending_investigation', 'reopened'].includes(item.state);
    if (filter === 'buyer') return ['awaiting_buyer', 'awaiting_approval'].includes(item.state);
    if (filter === 'closed') return ['resolved', 'escalated'].includes(item.state);
    return true;
  });

  return (
    <div className="mx-auto max-w-7xl p-4 sm:p-6">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-400">AI purchasing agent</p>
          <h1 className="mt-1 text-2xl font-semibold text-gray-100">Buyer exception queue</h1>
          <p className="mt-1 text-sm text-gray-500">Investigate recommendations, authorize decisions, and verify outcomes.</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={load} className="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-gray-300 hover:bg-gray-800">↻ Refresh</button>
          <button onClick={() => setShowCreate(true)} disabled={caseOptions.length === 0} className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-50">＋ New case</button>
        </div>
      </div>

      {counts && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Summary label="Needs agent" value={counts.agent} tone="sky" />
          <Summary label="Needs buyer" value={counts.buyer} tone="amber" />
          <Summary label="Resolved" value={counts.resolved} tone="emerald" />
          <Summary label="Escalated" value={counts.escalated} tone="red" />
        </div>
      )}

      {loading && <Spinner label="Loading cases…" />}
      {!loading && !!error && <ErrorBanner error={error} />}
      {!loading && !error && cases && cases.length === 0 && (
        <EmptyState>
          No cases found. If you just reset the demo, seed data may still be loading — refresh in a moment.
        </EmptyState>
      )}
      {!loading && !error && cases && cases.length > 0 && (
        <section>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-gray-100">Purchasing cases</h2>
            <p className="text-sm text-gray-500">Open a case to inspect evidence, the proposed action, approval policy, and validation result.</p>
          </div>
          <div className="flex rounded-lg border border-gray-800 bg-gray-950 p-1" aria-label="Filter cases">
            {(['all', 'agent', 'buyer', 'closed'] as const).map((value) => (
              <button
                key={value}
                onClick={() => setFilter(value)}
                aria-pressed={filter === value}
                className={`rounded-md px-3 py-1.5 text-xs font-medium ${filter === value ? 'bg-gray-800 text-white' : 'text-gray-500 hover:text-gray-300'}`}
              >
                {titleCase(value)}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto rounded-xl border border-gray-800 bg-gray-950/70">
          <table className="w-full min-w-[980px] text-left text-sm">
            <thead className="bg-gray-900 text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <ColumnHeader label="Case" help="The product and fulfillment node being investigated. Data as-of shows how current the operational snapshot is." />
                <ColumnHeader label="Incoming signal" help="The event that opened the case and its source. It is an input for investigation, not an approved purchasing decision." />
                <ColumnHeader label="Projected shortage" help="Demand the current inventory and confirmed incoming orders are projected to miss if no new action is taken." />
                <ColumnHeader label="Agent decision" help="The agent's conclusion about the incoming signal and the operational action it proposes after checking constraints." />
                <ColumnHeader label="Workflow" help="The case's current state, who must act next, when activity last occurred, and whether the latest run was live or replayed." />
                <th className="w-12 px-4 py-3 font-medium" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {visibleCases?.map((c) => (
                <tr
                  key={c.case_id}
                  className="group bg-gray-950/60 hover:bg-gray-900/90"
                >
                  <td className="px-4 py-4 align-top">
                    <div className="flex gap-3">
                      <CaseIcon state={c.state} />
                      <div>
                        <Link to={`/cases/${encodeURIComponent(c.case_id)}`} className="font-semibold text-gray-100 group-hover:text-sky-300">{c.title}</Link>
                        <p className="mt-1 text-xs text-gray-500">{c.fixture_id || 'Custom'} · {c.sku} · {c.node_id}</p>
                        <p className="mt-1 text-[11px] text-gray-600">Data as of {dateShort(c.data_as_of)}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-4 align-top">
                    <p className="font-medium text-gray-200">{signalText(c.trigger_type, c.recommended_qty)}</p>
                    <p className="mt-1 text-xs text-gray-500">Source: {c.signal_source}</p>
                  </td>
                  <td className="px-4 py-4 align-top">
                    <p className={c.projected_unmet_units > 0 ? 'font-semibold text-amber-300' : 'font-semibold text-emerald-300'}>
                      {c.projected_unmet_units > 0 ? `${num(c.projected_unmet_units)} units may go unfilled` : 'No projected shortage'}
                    </p>
                    <p className="mt-1 text-xs text-gray-500">{c.first_stockout_date ? `First stockout: ${dateShort(c.first_stockout_date)}` : 'Current plan covers forecast demand'}</p>
                  </td>
                  <td className="px-4 py-4 align-top">
                    {c.latest_disposition ? (
                      <>
                        <p className="font-medium text-gray-200">{titleCase(c.latest_disposition)} <span className="text-gray-600">→</span> {titleCase(c.latest_action_type || '')}</p>
                        <div className="mt-1 flex items-center gap-2 text-xs text-gray-500">
                          <VerdictBadge verdict={c.latest_verdict} />
                          {c.replan_count > 0 && <span>↻ {c.replan_count} replan</span>}
                        </div>
                      </>
                    ) : <p className="text-gray-500">Not reviewed yet</p>}
                  </td>
                  <td className="px-4 py-4 align-top">
                    <StateBadge state={c.state} />
                    <p className="mt-2 text-xs text-gray-500">Next: {titleCase(c.next_actor)}{c.latest_run_mode ? ` · ${titleCase(c.latest_run_mode)}` : ''}</p>
                    <p className="mt-1 text-[11px] text-gray-600">Updated {dateTimeShort(c.last_activity_at)}</p>
                  </td>
                  <td className="px-4 py-4 align-middle">
                    <Link to={`/cases/${encodeURIComponent(c.case_id)}`} aria-label={`Open ${c.title}`} className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-gray-700 text-gray-400 group-hover:border-sky-700 group-hover:text-sky-300">→</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {visibleCases?.length === 0 && <p className="rounded-lg border border-gray-800 p-6 text-center text-sm text-gray-500">No cases match this filter.</p>}
        </section>
      )}
      {showCreate && (
        <CreateCaseDialog
          options={caseOptions}
          onClose={() => setShowCreate(false)}
          onCreated={(caseId) => navigate(`/cases/${encodeURIComponent(caseId)}`)}
        />
      )}
    </div>
  );
}

function ColumnHeader({ label, help }: { label: string; help: string }) {
  const [position, setPosition] = useState<{ left: number; bottom: number } | null>(null);
  const tooltipId = `column-help-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
  const show = (element: HTMLElement) => {
    const rect = element.getBoundingClientRect();
    const width = 256;
    setPosition({
      left: Math.min(Math.max(12, rect.left + rect.width / 2 - width / 2), window.innerWidth - width - 12),
      bottom: window.innerHeight - rect.top + 8,
    });
  };
  return (
    <th className="px-4 py-3 font-medium">
      <span className="inline-flex items-center gap-1.5">
        {label}
        <button
          type="button"
          aria-label={`About ${label}`}
          aria-describedby={position ? tooltipId : undefined}
          onMouseEnter={(event) => show(event.currentTarget)}
          onMouseLeave={() => setPosition(null)}
          onFocus={(event) => show(event.currentTarget)}
          onBlur={() => setPosition(null)}
          className="flex h-4 w-4 items-center justify-center rounded-full border border-gray-600 text-[10px] normal-case text-gray-400 hover:border-sky-600 hover:text-sky-300 focus:border-sky-600 focus:text-sky-300 focus:outline-none"
        >
          i
        </button>
        {position && createPortal(
          <span
            id={tooltipId}
            role="tooltip"
            style={{ left: position.left, bottom: position.bottom }}
            className="fixed z-[100] w-64 rounded-lg border border-gray-700 bg-gray-950 p-3 text-left text-xs font-normal normal-case leading-5 tracking-normal text-gray-300 shadow-2xl"
          >
            {help}
          </span>,
          document.body,
        )}
      </span>
    </th>
  );
}

function signalText(type: string, quantity: number | null): string {
  if (type === 'recommendation' || type === 'buyer_recommendation') {
    return quantity == null ? 'Purchase recommendation' : `Purchase recommendation: ${num(quantity)} units`;
  }
  if (type === 'demand_spike') return 'Demand anomaly detected';
  if (type === 'supplier_shortfall') return 'Supplier shortfall reported';
  return titleCase(type);
}

function CaseIcon({ state }: { state: string }) {
  const closed = state === 'resolved';
  const escalated = state === 'escalated';
  return (
    <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border text-base ${closed ? 'border-emerald-800 bg-emerald-950/40 text-emerald-300' : escalated ? 'border-red-800 bg-red-950/40 text-red-300' : 'border-sky-800 bg-sky-950/40 text-sky-300'}`} aria-hidden>
      {closed ? '✓' : escalated ? '!' : '⌁'}
    </span>
  );
}

function Summary({ label, value, tone }: { label: string; value: number; tone: 'sky' | 'amber' | 'emerald' | 'red' }) {
  const colors = {
    sky: 'border-sky-900/70 text-sky-300',
    amber: 'border-amber-900/70 text-amber-300',
    emerald: 'border-emerald-900/70 text-emerald-300',
    red: 'border-red-900/70 text-red-300',
  };
  return (
    <div className={`rounded-xl border bg-gray-950 p-4 ${colors[tone]}`}>
      <p className="text-2xl font-semibold">{value}</p>
      <p className="mt-1 text-xs uppercase tracking-wide text-gray-500">{label}</p>
    </div>
  );
}
