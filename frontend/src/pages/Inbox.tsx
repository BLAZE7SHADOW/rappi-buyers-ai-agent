import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { StateBadge, VerdictBadge } from '../components/Badges';
import { EmptyState, ErrorBanner, Spinner } from '../components/StatusViews';
import { num, titleCase } from '../format';
import type { CaseListItem } from '../types';

export function Inbox() {
  const [cases, setCases] = useState<CaseListItem[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .listCases()
      .then((res) => setCases(res.cases))
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  return (
    <div className="mx-auto max-w-6xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">Purchasing cases</h1>
          <p className="mt-1 text-sm text-gray-500">Cases awaiting investigation, approval, or resolution.</p>
        </div>
        <button
          onClick={load}
          className="rounded-md border border-gray-700 bg-gray-900 px-3 py-1.5 text-sm text-gray-300 hover:bg-gray-800"
        >
          Refresh
        </button>
      </div>

      {loading && <Spinner label="Loading cases…" />}
      {!loading && error && <ErrorBanner error={error} />}
      {!loading && !error && cases && cases.length === 0 && (
        <EmptyState>
          No cases found. If you just reset the demo, seed data may still be loading — refresh in a moment.
        </EmptyState>
      )}
      {!loading && !error && cases && cases.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="bg-gray-900 text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-3 py-2 font-medium">Fixture</th>
                <th className="px-3 py-2 font-medium">SKU / Node</th>
                <th className="px-3 py-2 font-medium">Title</th>
                <th className="px-3 py-2 font-medium">Trigger</th>
                <th className="px-3 py-2 font-medium">State</th>
                <th className="px-3 py-2 font-medium">Replans</th>
                <th className="px-3 py-2 font-medium">Next actor</th>
                <th className="px-3 py-2 font-medium">Latest verdict</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {cases.map((c) => (
                <tr
                  key={c.case_id}
                  className="cursor-pointer bg-gray-950 hover:bg-gray-900"
                  onClick={() => (window.location.href = `/cases/${encodeURIComponent(c.case_id)}`)}
                >
                  <td className="px-3 py-2 align-top">
                    <Link
                      to={`/cases/${encodeURIComponent(c.case_id)}`}
                      className="font-mono text-xs text-sky-400 hover:underline"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {c.fixture_id}
                    </Link>
                  </td>
                  <td className="px-3 py-2 align-top text-gray-300">
                    {c.sku} <span className="text-gray-600">/</span> {c.node_id}
                  </td>
                  <td className="px-3 py-2 align-top text-gray-200">{c.title}</td>
                  <td className="px-3 py-2 align-top text-gray-400">
                    {titleCase(c.trigger_type)}
                    {c.recommended_qty != null && (
                      <span className="ml-1 text-gray-500">({num(c.recommended_qty)} units)</span>
                    )}
                  </td>
                  <td className="px-3 py-2 align-top">
                    <StateBadge state={c.state} />
                  </td>
                  <td className="px-3 py-2 align-top text-gray-400">{c.replan_count}</td>
                  <td className="px-3 py-2 align-top text-gray-300">{titleCase(c.next_actor)}</td>
                  <td className="px-3 py-2 align-top">
                    <VerdictBadge verdict={c.latest_verdict} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
