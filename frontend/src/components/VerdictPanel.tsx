import { VerdictBadge } from './Badges';
import { money, titleCase } from '../format';
import type { ActionItem, Verdict } from '../types';

export function VerdictPanel({ actions }: { actions: ActionItem[] }) {
  if (actions.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        No actions have been executed yet. A verdict appears here once an action runs and is independently
        validated.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      {actions.map((a) => (
        <div key={a.action_id} className="rounded-lg border border-gray-800 bg-gray-950 p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-sm font-medium text-gray-200">
                {titleCase(a.action_type)} {a.po_id && <span className="text-gray-500">· {a.po_id}</span>}
              </p>
              <p className="text-xs text-gray-500">
                State: {titleCase(a.state)} · Attempts: {a.attempts}
              </p>
            </div>
            <VerdictBadge verdict={a.verdict?.verdict ?? null} size="lg" />
          </div>

          {a.verdict ? <VerdictBody verdict={a.verdict} /> : (
            <p className="text-sm text-gray-500">Awaiting independent validation.</p>
          )}
        </div>
      ))}
    </div>
  );
}

function VerdictBody({ verdict }: { verdict: Verdict }) {
  const execChecks = verdict.checks.filter((c) => c.layer === 'execution');
  const bizChecks = verdict.checks.filter((c) => c.layer === 'business');
  const otherChecks = verdict.checks.filter((c) => c.layer !== 'execution' && c.layer !== 'business');

  const residual = verdict.residual_exposure as {
    unmet_units?: number;
    unmet_days?: string[];
    first_stockout_date?: string | null;
  };

  return (
    <div className="space-y-4">
      {/* Expected vs Actual vs Delta */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <KVBlock title="Expected" data={verdict.expected} />
        <KVBlock title="Actual" data={verdict.actual} />
        <KVBlock title="Delta" data={verdict.deltas} highlight />
      </div>

      {/* Checks by layer */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <CheckGroup title="Execution checks" checks={execChecks} />
        <CheckGroup title="Business outcome checks" checks={bizChecks} />
      </div>
      {otherChecks.length > 0 && <CheckGroup title="Other checks" checks={otherChecks} />}

      {/* Residual exposure */}
      {(residual.unmet_units ?? 0) > 0 && (
        <div className="rounded border border-amber-800/50 bg-amber-950/10 p-3 text-sm text-amber-200">
          <p className="font-semibold">Residual exposure</p>
          <p className="mt-1">
            {residual.unmet_units} units unmet
            {residual.first_stockout_date ? ` starting ${residual.first_stockout_date}` : ''}
            {residual.unmet_days && residual.unmet_days.length > 0
              ? ` across ${residual.unmet_days.length} day(s)`
              : ''}
            .
          </p>
        </div>
      )}

      {/* Follow-up */}
      {verdict.follow_up && (
        <p className="text-sm text-gray-400">
          <span className="font-medium text-gray-300">Follow-up: </span>
          {titleCase(verdict.follow_up)}
        </p>
      )}
    </div>
  );
}

function KVBlock({ title, data, highlight }: { title: string; data: Record<string, unknown>; highlight?: boolean }) {
  const entries = Object.entries(data || {});
  return (
    <div className="rounded border border-gray-800 p-3">
      <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">{title}</h4>
      {entries.length === 0 ? (
        <p className="text-xs text-gray-600">—</p>
      ) : (
        <dl className="space-y-0.5 text-sm">
          {entries.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-2">
              <dt className="text-gray-500">{formatKey(k)}</dt>
              <dd className={`font-mono ${highlight ? 'text-amber-300' : 'text-gray-200'}`}>
                {formatValue(k, v, highlight)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

/** Fields ending in `_minor` are integer cents and must never be shown raw. */
function isMoneyKey(key: string): boolean {
  return key.endsWith('_minor');
}

function formatKey(key: string): string {
  return titleCase(isMoneyKey(key) ? key.replace(/_minor$/, '') : key);
}

function formatValue(key: string, value: unknown, signed = false): string {
  if (value === null || value === undefined) return '—';
  if (isMoneyKey(key) && typeof value === 'number') {
    // Deltas read better with an explicit sign: -$800.00 beats $-800.00.
    return signed && value !== 0
      ? `${value < 0 ? '−' : '+'}${money(Math.abs(value))}`
      : money(value);
  }
  if (signed && typeof value === 'number' && value !== 0) {
    return `${value < 0 ? '−' : '+'}${Math.abs(value).toLocaleString('en-US')}`;
  }
  return String(value);
}

function CheckGroup({ title, checks }: { title: string; checks: { name: string; passed: boolean; detail: string }[] }) {
  return (
    <div className="rounded border border-gray-800 p-3">
      <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">{title}</h4>
      {checks.length === 0 ? (
        <p className="text-xs text-gray-600">None</p>
      ) : (
        <ul className="space-y-1.5 text-sm">
          {checks.map((c) => (
            <li key={c.name} className={c.passed ? 'text-emerald-300' : 'text-red-300'}>
              <span className="font-medium">{c.passed ? '✓' : '✗'} {titleCase(c.name)}</span>
              {c.detail && <p className="text-xs text-gray-400">{c.detail}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
