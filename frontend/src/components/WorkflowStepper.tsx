import { titleCase } from '../format';

const STEPS = ['investigate', 'decide', 'approve', 'execute', 'validate', 'resolve'];

function positionFor(state: string): number {
  if (['investigating', 'pending_investigation', 'awaiting_buyer', 'reopened'].includes(state)) return 0;
  if (state === 'awaiting_approval' || state === 'authorized') return 2;
  if (state === 'executing') return 3;
  if (state === 'validating' || state === 'awaiting_confirmation') return 4;
  return 5;
}

export function WorkflowStepper({ state }: { state: string }) {
  const active = positionFor(state);
  return (
    <ol aria-label="Purchasing workflow" className="grid grid-cols-3 gap-2 sm:grid-cols-6">
      {STEPS.map((step, index) => (
        <li key={step} className="min-w-0">
          <div className={`h-1 rounded-full ${index <= active ? 'bg-sky-500' : 'bg-gray-800'}`} />
          <p className={`mt-2 truncate text-xs ${index === active ? 'font-semibold text-sky-300' : 'text-gray-500'}`}>
            {titleCase(step)}
          </p>
        </li>
      ))}
    </ol>
  );
}
