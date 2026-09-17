import { useState } from 'react';
import { Pill } from './Badges';
import { titleCase } from '../format';
import type { Proposal } from '../types';

export function ProposalCard({
  proposal,
  caseState,
  onApprove,
  onDecline,
  onExecute,
  busy,
}: {
  proposal: Proposal;
  caseState: string;
  onApprove: () => Promise<void>;
  onDecline: (reason: string) => Promise<void>;
  onExecute: () => Promise<void>;
  busy: boolean;
}) {
  const [declineReason, setDeclineReason] = useState('');
  const [showDecline, setShowDecline] = useState(false);

  const showActions = caseState === 'proposed' || caseState === 'awaiting_approval' || caseState === 'awaiting_buyer';

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-950 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-gray-100">
            v{proposal.version} · {titleCase(proposal.disposition)} · {titleCase(proposal.action_type)}
          </span>
          <Pill tone="neutral">{titleCase(proposal.state)}</Pill>
        </div>
        {proposal.approval_required ? (
          <Pill tone="warn">Approval required</Pill>
        ) : (
          <Pill tone="good">Within autonomy limits</Pill>
        )}
      </div>

      <p className="text-sm text-gray-300">{proposal.rationale}</p>

      {proposal.approval_reason && (
        <p className="mt-2 text-xs text-amber-300">Why approval is needed: {proposal.approval_reason}</p>
      )}

      {proposal.important_factors.length > 0 && (
        <div className="mt-3">
          <h5 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Important factors</h5>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-sm text-gray-300">
            {proposal.important_factors.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}

      {proposal.assumptions.length > 0 && (
        <div className="mt-3">
          <h5 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Assumptions</h5>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-sm text-gray-400">
            {proposal.assumptions.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}

      {Object.keys(proposal.residual_exposure || {}).length > 0 && (
        <div className="mt-3">
          <h5 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Residual exposure</h5>
          <pre className="mt-1 overflow-x-auto rounded bg-black/30 p-2 text-xs text-gray-400">
            {JSON.stringify(proposal.residual_exposure, null, 2)}
          </pre>
        </div>
      )}

      {proposal.decline_reason && (
        <p className="mt-3 text-xs text-red-300">Declined: {proposal.decline_reason}</p>
      )}

      {showActions && proposal.state === 'proposed' && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {proposal.approval_required ? (
            <>
              <button
                disabled={busy}
                onClick={() => onApprove()}
                className="rounded-md bg-emerald-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-600 disabled:opacity-50"
              >
                Approve
              </button>
              {!showDecline ? (
                <button
                  disabled={busy}
                  onClick={() => setShowDecline(true)}
                  className="rounded-md border border-red-800 px-3 py-1.5 text-sm font-medium text-red-300 hover:bg-red-950/40 disabled:opacity-50"
                >
                  Decline
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
          ) : (
            <button
              disabled={busy}
              onClick={() => onExecute()}
              className="rounded-md bg-teal-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-teal-600 disabled:opacity-50"
            >
              Execute
            </button>
          )}
        </div>
      )}
    </div>
  );
}
