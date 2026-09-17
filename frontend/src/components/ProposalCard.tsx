import { useState } from 'react';
import { Pill } from './Badges';
import { dateShort, money, num, titleCase } from '../format';
import type { Proposal } from '../types';

export function ProposalCard({
  proposal,
  caseState,
  onApprove,
  onDecline,
  busy,
}: {
  proposal: Proposal;
  caseState: string;
  onApprove: () => Promise<void>;
  onDecline: (reason: string) => Promise<void>;
  busy: boolean;
}) {
  const [declineReason, setDeclineReason] = useState('');
  const [showDecline, setShowDecline] = useState(false);

  const showActions = caseState === 'awaiting_approval'
    && proposal.state === 'proposed'
    && proposal.approval_required;
  const simulation = proposal.simulation as {
    label?: string;
    supplier_id?: string | null;
    po_id?: string | null;
    qty?: number;
    expected_receipt_date?: string | null;
    incremental_cost_minor?: number;
    unmet_reduction?: number;
    residual_unmet?: number;
    before?: { total_unmet_units?: number };
    after?: { total_unmet_units?: number; closing_inventory?: number };
    checks?: { name: string; passed: boolean; binding_reason?: string }[];
  };
  const actionTitle = describeAction(proposal, simulation);

  return (
    <div className={`rounded-xl border p-5 ${showActions ? 'border-amber-500/80 bg-amber-950/15 shadow-xl shadow-amber-950/20' : 'border-gray-800 bg-gray-950'}`}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Recommended disposition · {titleCase(proposal.disposition)}</p>
          <h3 className="mt-1 text-xl font-semibold text-gray-100">{actionTitle}</h3>
          <p className="mt-1 text-xs text-gray-600">Decision version {proposal.version} · {proposal.proposal_id}</p>
        </div>
        <div className="flex items-center gap-2">
          <Pill tone="neutral">{titleCase(proposal.state)}</Pill>
        {proposal.approval_required ? (
          <Pill tone="warn">Human approval required</Pill>
        ) : (
          <Pill tone="good">Within autonomy limits</Pill>
        )}
        </div>
      </div>

      {proposal.approval_reason && (
        <div className="mt-4 rounded-lg border border-amber-800/60 bg-amber-950/20 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-amber-300">Why a buyer must decide</p>
          <p className="mt-1 text-sm leading-5 text-amber-100">{proposal.approval_reason}</p>
        </div>
      )}

      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <ProofMetric label="Affected quantity" value={simulation.qty ? `${num(simulation.qty)} units` : 'No new units'} />
        <ProofMetric label="Expected arrival" value={dateShort(simulation.expected_receipt_date)} />
        <ProofMetric label="Incremental cost" value={money(simulation.incremental_cost_minor)} />
        <ProofMetric label="Unmet after" value={`${num(simulation.after?.total_unmet_units)} units`} good={(simulation.after?.total_unmet_units ?? 0) === 0} />
      </div>

      {proposal.important_factors.length > 0 && (
        <div className="mt-3">
          <h5 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Why this action</h5>
          <ul className="mt-2 space-y-2 text-sm text-gray-300">
            {proposal.important_factors.map((f, i) => (
              <li key={i} className="grid grid-cols-[1.25rem_1fr] gap-2"><span className="text-sky-400">{i + 1}.</span><span>{f}</span></li>
            ))}
          </ul>
        </div>
      )}
      {proposal.important_factors.length === 0 && <p className="mt-3 text-sm leading-6 text-gray-300">{proposal.rationale}</p>}

      {!!simulation.checks?.length && (
        <div className="mt-4 rounded-lg border border-gray-800 bg-black/20 p-3">
          <div className="flex items-center justify-between gap-2">
            <h5 className="text-xs font-semibold uppercase tracking-wide text-gray-400">Constraints verified for this action</h5>
            <span className="text-xs text-gray-500">{simulation.checks.filter((check) => check.passed).length}/{simulation.checks.length} passed</span>
          </div>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {simulation.checks.map((check) => (
              <div key={check.name} className={`rounded-md border px-2.5 py-2 text-xs ${check.passed ? 'border-emerald-900/70 bg-emerald-950/20 text-emerald-300' : 'border-red-900/70 bg-red-950/20 text-red-300'}`}>
                <span className="font-semibold">{check.passed ? '✓' : '×'} {titleCase(check.name)}</span>
                {check.binding_reason && <p className="mt-1 leading-4 text-gray-500">{check.binding_reason}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {proposal.assumptions.length > 0 && (
        <details className="mt-3 rounded-lg border border-gray-800 px-3 py-2">
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-gray-500">{proposal.assumptions.length} assumption{proposal.assumptions.length === 1 ? '' : 's'} used</summary>
          <ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-gray-400">
            {proposal.assumptions.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </details>
      )}

      {proposal.decline_reason && (
        <p className="mt-3 text-xs text-red-300">Declined: {proposal.decline_reason}</p>
      )}

      {showActions && proposal.state === 'proposed' && (
        <div className="mt-5 rounded-xl border border-amber-700/60 bg-amber-950/30 p-4">
          <p className="mb-3 text-sm font-semibold text-amber-100">Your decision is required to continue</p>
          <p className="mb-3 text-xs leading-5 text-gray-400">Approval covers this supplier, quantity, date and cost. Constraints are checked again before execution.</p>
          <div className="flex flex-wrap items-center gap-2">
          {proposal.approval_required ? (
            <>
              <button
                disabled={busy}
                onClick={() => onApprove()}
                className="rounded-lg bg-amber-400 px-5 py-3 text-sm font-bold text-gray-950 shadow-lg shadow-amber-950/40 hover:bg-amber-300 disabled:opacity-50"
              >
                Approve and execute
              </button>
              {!showDecline ? (
                <button
                  disabled={busy}
                  onClick={() => setShowDecline(true)}
                  className="rounded-lg border border-red-800 px-4 py-2.5 text-sm font-medium text-red-300 hover:bg-red-950/40 disabled:opacity-50"
                >
                  Decline recommendation
                </button>
              ) : (
                <div className="flex items-center gap-2">
                  <input
                    value={declineReason}
                    onChange={(e) => setDeclineReason(e.target.value)}
                    placeholder="Reason for declining"
                    className="rounded-md border border-gray-700 bg-gray-900 px-2 py-1.5 text-sm text-gray-200"
                  />
                  <button
                    disabled={busy}
                    onClick={() => onDecline(declineReason)}
                    className="rounded-md bg-red-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-600 disabled:opacity-50"
                  >
                    Confirm decline
                  </button>
                </div>
              )}
            </>
          ) : null}
          </div>
        </div>
      )}
    </div>
  );
}

function describeAction(proposal: Proposal, simulation: { label?: string; supplier_id?: string | null; po_id?: string | null; qty?: number; expected_receipt_date?: string | null }): string {
  if (simulation.label) return simulation.label;
  if (proposal.action_type === 'expedite_po') {
    const poId = String(proposal.action_args.po_id || simulation.po_id || 'existing PO');
    const newDate = String(proposal.action_args.new_date || simulation.expected_receipt_date || '');
    return `Expedite ${poId}${newDate ? ` to ${dateShort(newDate)}` : ''}`;
  }
  if (proposal.action_type === 'create_po') {
    const quantity = Number(proposal.action_args.qty || simulation.qty || 0);
    const supplier = String(proposal.action_args.supplier_id || simulation.supplier_id || 'selected supplier');
    return `Create a ${num(quantity)}-unit purchase order with ${supplier}`;
  }
  if (proposal.action_type === 'keep_plan') return 'Keep the current purchasing plan';
  if (proposal.action_type === 'none') return 'Escalate without placing an order';
  return titleCase(proposal.action_type);
}

function ProofMetric({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
      <p className="text-[11px] font-medium uppercase tracking-wide text-gray-500">{label}</p>
      <p className={`mt-1 text-sm font-semibold ${good ? 'text-emerald-300' : 'text-gray-200'}`}>{value}</p>
    </div>
  );
}
