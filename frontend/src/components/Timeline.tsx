import { useState } from 'react';
import type { CaseEvent } from '../types';

const KIND_META: Record<string, { icon: string; color: string }> = {
  tool_call: { icon: '🔧', color: 'text-sky-300' },
  observation: { icon: '👁', color: 'text-gray-300' },
  proposal: { icon: '📝', color: 'text-violet-300' },
  question: { icon: '❓', color: 'text-amber-300' },
  answer: { icon: '💬', color: 'text-amber-200' },
  approval: { icon: '✅', color: 'text-emerald-300' },
  action: { icon: '⚙️', color: 'text-teal-300' },
  verdict: { icon: '⚖️', color: 'text-fuchsia-300' },
  state: { icon: '🔄', color: 'text-gray-400' },
  error: { icon: '⛔', color: 'text-red-300' },
};

export function Timeline({ events }: { events: CaseEvent[] }) {
  const [open, setOpen] = useState<Set<number>>(new Set());

  if (events.length === 0) {
    return <p className="text-sm text-gray-500">No events recorded yet. Run the agent to generate activity.</p>;
  }

  const toggle = (seq: number) => {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(seq)) next.delete(seq);
      else next.add(seq);
      return next;
    });
  };

  return (
    <ol className="space-y-1">
      {events.map((e) => {
        const meta = KIND_META[e.kind] || { icon: '•', color: 'text-gray-400' };
        const isOpen = open.has(e.seq);
        return (
          <li key={e.seq} className="rounded border border-gray-800">
            <button
              type="button"
              onClick={() => toggle(e.seq)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-900"
            >
              <span aria-hidden>{meta.icon}</span>
              <span className={`text-xs font-semibold uppercase tracking-wide ${meta.color}`}>{e.kind}</span>
              <span className="flex-1 truncate text-gray-300">{e.label}</span>
              <span className="text-xs text-gray-600">{e.created_at ? new Date(e.created_at).toLocaleTimeString() : ''}</span>
              <span className="text-xs text-gray-600">{isOpen ? '▲' : '▼'}</span>
            </button>
            {isOpen && (
              <pre className="overflow-x-auto border-t border-gray-800 bg-black/30 p-3 text-xs text-gray-400">
                {JSON.stringify(e.payload, null, 2)}
              </pre>
            )}
          </li>
        );
      })}
    </ol>
  );
}
