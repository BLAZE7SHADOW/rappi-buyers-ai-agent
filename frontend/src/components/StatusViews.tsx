import { ApiError } from '../api/client';

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-gray-400">
      <svg className="h-4 w-4 animate-spin text-gray-400" viewBox="0 0 24 24" fill="none">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
      </svg>
      {label && <span>{label}</span>}
    </div>
  );
}

export function ErrorBanner({ error }: { error: unknown }) {
  if (error instanceof ApiError) {
    if (error.detail.error === 'NO_PROVIDER_KEY') {
      return (
        <div className="rounded-lg border border-amber-700/50 bg-amber-950/30 p-4 text-sm text-amber-200">
          <p className="font-semibold">No LLM provider key configured</p>
          <p className="mt-1 text-amber-300/90">
            {error.detail.message} Set <code className="rounded bg-black/30 px-1 py-0.5">GEMINI_API_KEY</code> (or{' '}
            <code className="rounded bg-black/30 px-1 py-0.5">ANTHROPIC_API_KEY</code>) in the backend's{' '}
            <code className="rounded bg-black/30 px-1 py-0.5">.env</code> file and restart the backend, then try
            again.
          </p>
        </div>
      );
    }
    return (
      <div className="rounded-lg border border-red-700/50 bg-red-950/30 p-4 text-sm text-red-200">
        <p className="font-semibold">{error.detail.error || 'Request failed'}</p>
        <p className="mt-1 text-red-300/90">{error.detail.message}</p>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-red-700/50 bg-red-950/30 p-4 text-sm text-red-200">
      <p className="font-semibold">Something went wrong</p>
      <p className="mt-1 text-red-300/90">{String(error)}</p>
    </div>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-gray-700 p-8 text-center text-sm text-gray-500">
      {children}
    </div>
  );
}
