import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { WorkflowStepper } from './WorkflowStepper';

describe('WorkflowStepper', () => {
  it('shows validation as the active stage while waiting for supplier confirmation', () => {
    render(<WorkflowStepper state="awaiting_confirmation" />);
    expect(screen.getByText('Validate')).toHaveClass('text-sky-300');
  });

  it('returns reopened cases to investigation', () => {
    render(<WorkflowStepper state="reopened" />);
    expect(screen.getByText('Investigate')).toHaveClass('text-sky-300');
  });
});
