import { useState } from 'react';

const BEHAVIORS = ['confirm_full', 'confirm_partial', 'confirm_late', 'reject', 'timeout_after_success'];

export function ControlsBar({
  running,
  onRun,
  onReset,
  onInjectBehavior,
  currentBehavior,
}: {
  running: boolean;
  onRun: () => Promise<void>;
  onReset: () => Promise<void>;
  onInjectBehavior: (behavior: string) => Promise<void>;
  currentBehavior: string;
}) {
  const [confirmingReset, setConfirmingReset] = useState(false);
  const [behavior, setBehavior] = useState(currentBehavior);

  return (
    <div className="rounded-lg border border-violet-800/50 bg-violet-950/10 p-4">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-violet-300">
          Simulation controls
        </span>
        <span className="text-xs text-gray-500">— demo-only tools, not a real supplier integration</span>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button
          disabled={running}
          onClick={() => onRun()}
          className="flex items-center gap-2 rounded-md bg-sky-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-600 disabled:opacity-50"
        >
          {running && (
            <svg className="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
            </svg>
          )}
          {running ? 'Running agent…' : 'Run agent'}
        </button>

        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-400">Supplier behaviour:</label>
          <select
            value={behavior}
            onChange={(e) => {
              setBehavior(e.target.value);
              onInjectBehavior(e.target.value);
            }}
            className="rounded-md border border-gray-700 bg-gray-900 px-2 py-1.5 text-sm text-gray-200"
          >
            {BEHAVIORS.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </div>

        <div className="ml-auto">
          {!confirmingReset ? (
            <button
              onClick={() => setConfirmingReset(true)}
              className="rounded-md border border-red-800 px-3 py-1.5 text-sm text-red-300 hover:bg-red-950/40"
            >
              Reset demo
            </button>
          ) : (
            <span className="flex items-center gap-2 text-sm text-red-300">
              Wipe and reseed all demo data?
              <button
                onClick={() => {
                  setConfirmingReset(false);
                  onReset();
                }}
                className="rounded-md bg-red-700 px-2 py-1 text-xs font-medium text-white hover:bg-red-600"
              >
                Confirm
              </button>
              <button
                onClick={() => setConfirmingReset(false)}
                className="rounded-md border border-gray-700 px-2 py-1 text-xs text-gray-300 hover:bg-gray-800"
              >
                Cancel
              </button>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
