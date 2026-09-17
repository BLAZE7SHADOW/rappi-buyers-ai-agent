import { Fragment, useState } from 'react';
import { Pill } from './Badges';
import { dateShort, money, num, titleCase } from '../format';
import type { Candidate } from '../types';

export function CandidatesTable({ candidates }: { candidates: Candidate[] }) {
  const [expanded, setExpanded] = useState<number | null>(null);

  if (candidates.length === 0) {
    return <p className="text-sm text-gray-500">No candidate plans have been simulated yet.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800">
      <table className="w-full min-w-[820px] text-left text-sm">
        <thead className="bg-gray-900 text-xs uppercase tracking-wide text-gray-500">
          <tr>
            <th className="px-3 py-2 font-medium">Plan</th>
            <th className="px-3 py-2 font-medium">Qty</th>
            <th className="px-3 py-2 font-medium">Arrival</th>
            <th className="px-3 py-2 font-medium">Cost</th>
            <th className="px-3 py-2 font-medium">Unmet after</th>
            <th className="px-3 py-2 font-medium">Feasible?</th>
            <th className="px-3 py-2 font-medium" />
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {candidates.map((c, i) => (
            <Fragment key={i}>
              <tr
                className={`cursor-pointer bg-gray-950 hover:bg-gray-900 ${!c.feasible ? 'opacity-50' : ''}`}
                onClick={() => setExpanded(expanded === i ? null : i)}
              >
                <td className={`px-3 py-2 ${!c.feasible ? 'line-through decoration-gray-600' : 'text-gray-100'}`}>
                  {c.label}
                </td>
                <td className="px-3 py-2 text-gray-300">{c.qty != null ? num(c.qty) : '—'}</td>
                <td className="px-3 py-2 text-gray-300">{dateShort(c.expected_receipt_date)}</td>
                <td className="px-3 py-2 text-gray-300">{money(c.incremental_cost_minor)}</td>
                <td className="px-3 py-2 text-gray-300">{num(c.after.total_unmet_units)}</td>
                <td className="px-3 py-2">
                  {c.feasible ? <Pill tone="good">Feasible</Pill> : <Pill tone="bad">Infeasible</Pill>}
                </td>
                <td className="px-3 py-2 text-xs text-gray-500">{expanded === i ? '▲' : '▼'}</td>
              </tr>
              {expanded === i && (
                <tr className="bg-gray-900/60">
                  <td colSpan={7} className="px-3 py-3">
                    {!c.feasible && c.binding_constraints.length > 0 && (
                      <div className="mb-2 rounded border border-red-800/50 bg-red-950/20 p-2 text-xs text-red-300">
                        <span className="font-semibold">Why unavailable: </span>
                        {c.binding_constraints.join('; ')}
                      </div>
                    )}
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                      {c.checks.map((chk) => (
                        <div
                          key={chk.name}
                          className={`rounded border px-2 py-1.5 text-xs ${
                            chk.passed
                              ? 'border-emerald-800/40 bg-emerald-950/10 text-emerald-300'
                              : 'border-red-800/40 bg-red-950/10 text-red-300'
                          }`}
                        >
                          <span className="font-medium">{chk.passed ? '✓' : '✗'} {titleCase(chk.name)}</span>
                          {chk.binding_reason && <p className="mt-0.5 text-gray-400">{chk.binding_reason}</p>}
                        </div>
                      ))}
                    </div>
                    <p className="mt-2 text-xs text-gray-500">
                      Unmet reduction: {num(c.unmet_reduction)} units · Residual unmet: {num(c.residual_unmet)} units
                    </p>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
