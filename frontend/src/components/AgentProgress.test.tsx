import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { CaseEvent } from '../types';
import { AgentProgress } from './AgentProgress';

const events: CaseEvent[] = [
  { seq: 1, kind: 'state', label: 'Agent run started', payload: { run_id: 'RUN-1' }, created_at: '2026-09-18T10:00:00Z' },
  { seq: 2, kind: 'tool_call', label: 'get_case_context', payload: { run_id: 'RUN-1', tool: 'get_case_context' }, created_at: '2026-09-18T10:00:01Z' },
  { seq: 3, kind: 'observation', label: 'get_case_context result', payload: { run_id: 'RUN-1', tool: 'get_case_context', result: {} }, created_at: '2026-09-18T10:00:02Z' },
  { seq: 4, kind: 'tool_call', label: 'get_inventory', payload: { run_id: 'RUN-1', tool: 'get_inventory', args: { reason: 'I need sellable stock before deciding whether another order is necessary.' } }, created_at: '2026-09-18T10:00:03Z' },
];

describe('AgentProgress', () => {
  it('shows only the path the agent actually chose in buyer language', () => {
    render(<AgentProgress events={events} running />);

    expect(screen.getByText('Choosing next step')).toBeInTheDocument();
    expect(screen.getByText('Read the incoming purchasing signal')).toBeInTheDocument();
    expect(screen.getByText('Checked sellable inventory')).toBeInTheDocument();
    expect(screen.getByText('I need sellable stock before deciding whether another order is necessary.')).toBeInTheDocument();
    expect(screen.getByText('In progress')).toBeInTheDocument();
    expect(screen.queryByText('Investigated demand')).not.toBeInTheDocument();
    expect(screen.queryByText('get_inventory')).not.toBeInTheDocument();
  });
});
