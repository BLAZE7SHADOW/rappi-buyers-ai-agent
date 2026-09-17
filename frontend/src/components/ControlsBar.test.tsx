import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ControlsBar } from './ControlsBar';

const defaults = {
  running: false,
  onRun: vi.fn(async () => undefined),
  onReset: vi.fn(async () => undefined),
  onInjectBehavior: vi.fn(async () => undefined),
  currentBehavior: 'confirm_partial',
  canRun: true,
  liveAvailable: false,
  replayAvailable: true,
  nextActor: 'Agent',
};

describe('ControlsBar', () => {
  it('makes recorded replay available when no live key is configured', () => {
    render(<ControlsBar {...defaults} />);
    expect(screen.getByRole('button', { name: 'Run live agent' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Replay recorded agent' })).toBeEnabled();
  });

  it('prevents all agent runs when the workflow is waiting on another actor', () => {
    render(<ControlsBar {...defaults} canRun={false} nextActor="Buyer" liveAvailable />);
    expect(screen.getByText('Waiting on Buyer.')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Run live agent' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Replay recorded agent' })).toBeDisabled();
  });

  it('forwards the selected supplier behavior', () => {
    const onInjectBehavior = vi.fn(async () => undefined);
    render(<ControlsBar {...defaults} onInjectBehavior={onInjectBehavior} />);
    fireEvent.change(screen.getByLabelText('Next supplier response'), { target: { value: 'reject' } });
    expect(onInjectBehavior).toHaveBeenCalledWith('reject');
  });
});
