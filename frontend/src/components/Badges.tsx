import { titleCase } from '../format';
import type { VerdictKind } from '../types';

const STATE_COLORS: Record<string, string> = {
  investigating: 'bg-sky-900/40 text-sky-300 border-sky-700/50',
  pending_investigation: 'bg-sky-900/40 text-sky-300 border-sky-700/50',
  reopened: 'bg-amber-900/40 text-amber-300 border-amber-700/50',
  awaiting_buyer: 'bg-violet-900/40 text-violet-300 border-violet-700/50',
  awaiting_approval: 'bg-violet-900/40 text-violet-300 border-violet-700/50',
  authorized: 'bg-teal-900/40 text-teal-300 border-teal-700/50',
  executing: 'bg-teal-900/40 text-teal-300 border-teal-700/50',
  awaiting_confirmation: 'bg-amber-900/40 text-amber-300 border-amber-700/50',
  validating: 'bg-teal-900/40 text-teal-300 border-teal-700/50',
  resolved: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/50',
  escalated: 'bg-red-900/40 text-red-300 border-red-700/50',
};

export function StateBadge({ state }: { state: string }) {
  const cls = STATE_COLORS[state] || 'bg-gray-800 text-gray-300 border-gray-700';
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ${cls}`}>
      {titleCase(state)}
    </span>
  );
}

const VERDICT_COLORS: Record<VerdictKind, string> = {
  PASS: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/50',
  PARTIAL: 'bg-amber-900/40 text-amber-300 border-amber-700/50',
  FAIL: 'bg-red-900/40 text-red-300 border-red-700/50',
  UNKNOWN: 'bg-gray-800 text-gray-400 border-gray-700',
};

export function VerdictBadge({ verdict, size = 'sm' }: { verdict: VerdictKind | null; size?: 'sm' | 'lg' }) {
  if (!verdict) {
    return (
      <span className="inline-flex items-center rounded-full border border-gray-700 bg-gray-800 px-2.5 py-0.5 text-xs font-medium text-gray-400">
        No verdict yet
      </span>
    );
  }
  const cls = VERDICT_COLORS[verdict];
  const sizeCls = size === 'lg' ? 'text-2xl px-5 py-2 font-bold' : 'text-xs px-2.5 py-0.5 font-medium';
  return (
    <span className={`inline-flex items-center rounded-full border ${cls} ${sizeCls}`}>
      {verdict}
    </span>
  );
}

export function Pill({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: 'neutral' | 'good' | 'bad' | 'warn' }) {
  const tones: Record<string, string> = {
    neutral: 'bg-gray-800 text-gray-300 border-gray-700',
    good: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/50',
    bad: 'bg-red-900/40 text-red-300 border-red-700/50',
    warn: 'bg-amber-900/40 text-amber-300 border-amber-700/50',
  };
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}
