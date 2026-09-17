import { useState } from 'react';

const BEHAVIORS = ['confirm_full', 'confirm_partial', 'confirm_late', 'reject', 'timeout_after_success'];

export function ControlsBar({
  running,
  onRun,
  onReset,
  onInjectBehavior,
  currentBehavior,
  canRun,
  liveAvailable,
  replayAvailable,
  nextActor,
}: {
  running: boolean;
  onRun: (mode: 'live' | 'replay') => Promise<void>;
  onReset: () => Promise<void>;
  onInjectBehavior: (behavior: string) => Promise<void>;
  currentBehavior: string;
  canRun: boolean;
  liveAvailable: boolean;
  replayAvailable: boolean;
  nextActor: string;
}) {
  const [confirmingReset, setConfirmingReset] = useState(false);
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-950/70 p-4 shadow-lg shadow-black/10">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-sky-300">Next step</p>
          <p className="mt-1 text-sm text-gray-400">
            {canRun ? 'Investigate this case with the purchasing agent.' : `Waiting on ${nextActor}.`}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button
          disabled={running || !canRun || !liveAvailable}
          onClick={() => onRun('live')}
          className="flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {running && (
            <svg className="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
            </svg>
          )}
          {running ? 'Running agent…' : 'Run live agent'}
        </button>

        <button
          disabled={running || !canRun || !replayAvailable}
          onClick={() => onRun('replay')}
          className="rounded-lg border border-violet-700 bg-violet-950/30 px-4 py-2 text-sm font-semibold text-violet-200 hover:bg-violet-900/40 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Replay recorded agent
        </button>

        {!liveAvailable && <span className="text-xs text-gray-500">Add an API key to enable live runs.</span>}
        {!replayAvailable && <span className="text-xs text-gray-500">Recorded replay is only available for evaluation fixtures.</span>}

        <details className="w-full border-t border-gray-800 pt-3">
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-gray-500">
            Demo controls
          </summary>
          <div className="mt-3 flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
          <label htmlFor="supplier-behavior" className="text-xs text-gray-400">Next supplier response</label>
          <select
            id="supplier-behavior"
            value={currentBehavior}
            onChange={(e) => {
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
        </details>
      </div>
    </div>
  );
}
