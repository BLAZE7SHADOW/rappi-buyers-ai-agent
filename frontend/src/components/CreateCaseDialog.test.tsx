import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import { CreateCaseDialog } from './CreateCaseDialog';

const option = {
  sku: 'SKU-1001',
  node_id: 'NODE-BOG',
  product_name: 'Sparkling Water',
  node_name: 'Bogota FC',
  as_of_date: '2026-09-17',
  usable_inventory: 1000,
  forecast_units: 2800,
  available_budget_minor: 900000,
  storage_headroom_m3: 180,
  eligible_suppliers: 2,
  projected_unmet_units: 400,
};

afterEach(() => vi.restoreAllMocks());

describe('CreateCaseDialog', () => {
  it('previews system constraints and creates a buyer recommendation', async () => {
    const create = vi.spyOn(api, 'createCase').mockResolvedValue({
      case_id: 'CASE-USER-1234',
      state: 'investigating',
    });
    const onCreated = vi.fn();

    render(<CreateCaseDialog options={[option]} onClose={() => undefined} onCreated={onCreated} />);

    expect(screen.getByText('1,000 units')).toBeInTheDocument();
    expect(screen.getByText('$9,000.00')).toBeInTheDocument();
    expect(screen.getByText('400 units exposed')).toBeInTheDocument();
    expect(screen.getByText(/buyer cannot override these facts/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/recommended purchase quantity/i), {
      target: { value: '725' },
    });
    fireEvent.change(screen.getByLabelText(/why was this case raised/i), {
      target: { value: 'Launch buffer review' },
    });
    fireEvent.click(screen.getByRole('button', { name: /create and investigate/i }));

    await waitFor(() => expect(create).toHaveBeenCalledWith({
      sku: 'SKU-1001',
      node_id: 'NODE-BOG',
      recommended_qty: 725,
      reason: 'Launch buffer review',
    }));
    expect(onCreated).toHaveBeenCalledWith('CASE-USER-1234');
  });
});
