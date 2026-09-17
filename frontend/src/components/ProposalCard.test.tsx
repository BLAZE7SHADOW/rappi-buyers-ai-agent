import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Proposal } from '../types';
import { ProposalCard } from './ProposalCard';

const proposal: Proposal = {
  proposal_id: 'PROP-1',
  version: 1,
  disposition: 'reject',
  action_type: 'expedite_po',
  action_args: { po_id: 'PO-501', new_date: '2026-09-27' },
  rationale: 'The recommendation buys unnecessary volume; moving confirmed supply closes the timing gap.',
  important_factors: ['Existing supply is sufficient in total.'],
  assumptions: [],
  residual_exposure: { unmet_units: 0 },
  simulation: {
    label: '',
    po_id: 'PO-501',
    qty: 2000,
    expected_receipt_date: '2026-09-27',
    incremental_cost_minor: 45000,
    unmet_reduction: 400,
    residual_unmet: 0,
    after: { total_unmet_units: 0 },
    checks: [{ name: 'budget', passed: true, binding_reason: '$450 within available budget.' }],
  },
  approval_required: true,
  approval_reason: 'Buyer approval required because the expedite fee exceeds the autonomy limit.',
  state: 'proposed',
  decline_reason: null,
};

describe('ProposalCard', () => {
  it('presents the exact action and high-risk approval in buyer language', () => {
    const approve = vi.fn().mockResolvedValue(undefined);
    render(<ProposalCard proposal={proposal} caseState="awaiting_approval" busy={false} onApprove={approve} onDecline={vi.fn()} />);

    expect(screen.getByText('Expedite PO-501 to Sep 27')).toBeInTheDocument();
    expect(screen.getByText(/why a buyer must decide/i)).toBeInTheDocument();
    expect(screen.getByText(/constraints are checked again before execution/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /approve and execute/i }));
    expect(approve).toHaveBeenCalledOnce();
  });

  // The gate reason text reads as its opposite under the wrong heading, so each
  // outcome must be labelled with the decision that actually applied.
  it('labels an autonomous plan as authorized rather than awaiting a buyer', () => {
    const autonomous: Proposal = {
      ...proposal,
      approval_required: false,
      approval_reason: 'Within delegated authority: $500.00 spend, $0.00 fees, no residual shortage.',
    };
    render(<ProposalCard proposal={autonomous} caseState="resolved" busy={false} onApprove={vi.fn()} onDecline={vi.fn()} />);

    expect(screen.getByText(/authorized automatically under delegated authority/i)).toBeInTheDocument();
    expect(screen.getByText(/the policy gate ran server-side/i)).toBeInTheDocument();
    expect(screen.queryByText(/why a buyer must decide/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /approve and execute/i })).not.toBeInTheDocument();
  });

  it('shows a blocked plan as unwaivable and offers no approval control', () => {
    const blocked: Proposal = {
      ...proposal,
      state: 'blocked',
      approval_reason: 'Hard constraint not satisfied: $12,000.00 exceeds available budget.',
    };
    render(<ProposalCard proposal={blocked} caseState="investigating" busy={false} onApprove={vi.fn()} onDecline={vi.fn()} />);

    expect(screen.getByText(/blocked by a hard constraint/i)).toBeInTheDocument();
    expect(screen.getByText(/approval cannot waive this/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /approve and execute/i })).not.toBeInTheDocument();
  });
});
