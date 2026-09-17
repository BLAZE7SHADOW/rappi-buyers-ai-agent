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
});
