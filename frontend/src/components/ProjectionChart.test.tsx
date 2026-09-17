import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ProjectionChart } from './ProjectionChart';
import type { ProjectionDay } from '../types';

const daily: ProjectionDay[] = [
  { day: '2026-09-26', opening: 200, receipts: 0, demand: 100, served: 100, unmet: 0, closing: 100, below_safety: true },
  { day: '2026-09-27', opening: 100, receipts: 0, demand: 200, served: 100, unmet: 100, closing: 0, below_safety: true },
  { day: '2026-09-28', opening: 0, receipts: 0, demand: 100, served: 0, unmet: 100, closing: 0, below_safety: true },
  { day: '2026-10-01', opening: 0, receipts: 2_000, demand: 100, served: 100, unmet: 0, closing: 1_900, below_safety: false },
];

describe('ProjectionChart', () => {
  it('makes the shortage, safety target, receipt, and first failed day visible', () => {
    render(<ProjectionChart daily={daily} safetyStock={200} />);

    expect(screen.getByText('Projected closing inventory by day')).toBeInTheDocument();
    expect(screen.getByText('Safety stock 200')).toBeInTheDocument();
    expect(screen.getByText('+2,000 receipt')).toBeInTheDocument();
    expect(screen.getByText('SHORTAGE WINDOW · 200 UNITS UNFILLED')).toBeInTheDocument();
    expect(screen.getByText(/Sep 27.*first shortage day/)).toBeInTheDocument();
    expect(screen.getByText('100 units unfilled')).toBeInTheDocument();
  });
});
