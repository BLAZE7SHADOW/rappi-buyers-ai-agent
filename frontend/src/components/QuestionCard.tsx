import { useState } from 'react';
import type { Interaction } from '../types';

export function QuestionCard({
  interaction,
  onRespond,
  busy,
}: {
  interaction: Interaction;
  onRespond: (answer: string) => Promise<void>;
  busy: boolean;
}) {
  const [text, setText] = useState('');

  const submit = (answer: string) => {
    if (!answer.trim()) return;
    onRespond(answer);
  };

  return (
    <div className="rounded-lg border border-amber-800/50 bg-amber-950/10 p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-amber-400">Pending question</p>
      <p className="mt-1 text-sm text-gray-100">{interaction.question}</p>
      {interaction.recommendation && (
        <p className="mt-1 text-xs text-gray-400">Agent recommendation: {interaction.recommendation}</p>
      )}

      {interaction.options.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {interaction.options.map((opt) => (
            <button
              key={opt}
              disabled={busy}
              onClick={() => submit(opt)}
              className="rounded-md border border-gray-700 bg-gray-900 px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-800 disabled:opacity-50"
            >
              {opt}
            </button>
          ))}
        </div>
      )}

      <div className="mt-3 flex items-center gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Type a custom answer"
          className="flex-1 rounded-md border border-gray-700 bg-gray-900 px-2 py-1.5 text-sm text-gray-200"
        />
        <button
          disabled={busy || !text.trim()}
          onClick={() => submit(text)}
          className="rounded-md bg-amber-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-600 disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </div>
  );
}
