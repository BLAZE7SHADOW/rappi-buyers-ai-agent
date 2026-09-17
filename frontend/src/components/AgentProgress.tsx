import { dateShort, num, titleCase } from '../format';
import type { CaseEvent } from '../types';

type Activity = {
  seq: number;
  title: string;
  reason: string;
  outcome: string;
  state: 'complete' | 'active' | 'issue';
  createdAt: string | null;
};

export function AgentProgress({ events, running }: { events: CaseEvent[]; running: boolean }) {
  const latestStart = events.filter((event) => event.label === 'Agent run started').at(-1);
  const runEvents = latestStart ? events.filter((event) => event.seq >= latestStart.seq) : [];
  const activities = buildActivities(runEvents);
  const runNumber = events.filter((event) => event.label === 'Agent run started').length;
  const finished = runEvents.some((event) => event.label === 'Agent run finished');
  const choosingNext = running && !activities.some((activity) => activity.state === 'active');

  return (
    <section className="overflow-hidden rounded-2xl border border-gray-800 bg-gray-950" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-800 px-5 py-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-sky-400">Agent investigation {runNumber > 1 ? `· Replan ${runNumber - 1}` : ''}</p>
          <h2 className="mt-1 text-lg font-semibold text-gray-100">Path chosen for this case</h2>
          <p className="mt-1 text-xs text-gray-500">This sequence comes from the agent’s actual choices. It can skip, repeat or add checks as the evidence changes.</p>
        </div>
        <div className="flex items-center gap-2">
          {running && <span className="h-2 w-2 animate-pulse rounded-full bg-sky-400" />}
          <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${running ? 'border-sky-700 bg-sky-950/60 text-sky-300' : finished ? 'border-emerald-800 bg-emerald-950/40 text-emerald-300' : 'border-gray-700 text-gray-400'}`}>
            {running ? 'Choosing next step' : finished ? `${activities.length} actions completed` : 'Not started'}
          </span>
        </div>
      </div>

      {activities.length === 0 && !running ? (
        <div className="px-5 py-6 text-sm text-gray-500">No investigation path exists yet. Run the agent and it will choose what to inspect from the case signal.</div>
      ) : (
        <ol className="divide-y divide-gray-800/80">
          {activities.map((activity) => (
            <li key={activity.seq} className={`grid grid-cols-[2.25rem_1fr_auto] gap-3 px-5 py-4 ${activity.state === 'active' ? 'bg-sky-950/25' : ''}`}>
              <ActivityMarker state={activity.state} />
              <div className="min-w-0">
                <p className="text-sm font-semibold text-gray-100">{activity.title}</p>
                <p className="mt-1 text-xs leading-5 text-gray-400"><span className="font-semibold text-gray-500">Why:</span> {activity.reason}</p>
                {activity.state !== 'active' && <p className={`mt-0.5 text-xs leading-5 ${activity.state === 'issue' ? 'text-red-300' : 'text-gray-500'}`}><span className="font-semibold">Result:</span> {activity.outcome}</p>}
              </div>
              <span className={`pt-1 text-[11px] font-semibold uppercase tracking-wide ${activity.state === 'active' ? 'text-sky-300' : activity.state === 'issue' ? 'text-red-300' : 'text-emerald-400'}`}>
                {activity.state === 'active' ? 'In progress' : activity.state === 'issue' ? 'Issue' : eventTime(activity.createdAt) || 'Done'}
              </span>
            </li>
          ))}
          {choosingNext && (
            <li className="grid grid-cols-[2.25rem_1fr] gap-3 bg-sky-950/15 px-5 py-4">
              <ActivityMarker state="active" />
              <div><p className="text-sm font-semibold text-sky-100">Choosing the next investigation step</p><p className="mt-1 text-xs text-gray-500">The agent is deciding whether it has enough evidence, needs another check, should ask the buyer, or can propose an action.</p></div>
            </li>
          )}
        </ol>
      )}
    </section>
  );
}

function buildActivities(events: CaseEvent[]): Activity[] {
  return events.filter((event) => event.kind === 'tool_call').map((call) => {
    const tool = String(call.payload.tool || call.label);
    const runId = call.payload.run_id;
    const resultEvent = events.find((event) => event.seq > call.seq && event.kind === 'observation' && event.payload.tool === tool && event.payload.run_id === runId);
    const args = asRecord(call.payload.args);
    const result = asRecord(resultEvent?.payload.result);
    const error = result.error ? String(result.message || result.error) : '';
    const copy = describe(tool, args, result);
    return {
      seq: call.seq,
      title: copy.title,
      reason: typeof args.reason === 'string' && args.reason.trim() ? args.reason : copy.reason,
      outcome: error || copy.outcome,
      state: error ? 'issue' : resultEvent ? 'complete' : 'active',
      createdAt: resultEvent?.created_at || call.created_at,
    };
  });
}

function describe(tool: string, args: Record<string, unknown>, result: Record<string, unknown>): { title: string; reason: string; outcome: string } {
  if (tool === 'get_case_context') return { title: 'Read the incoming purchasing signal', reason: 'Establish what changed, what was recommended and which policy applies.', outcome: 'Case scope and known information established.' };
  if (tool === 'get_inventory') return { title: 'Checked sellable inventory', reason: 'Separate stock that can serve demand from reserved, quarantined or damaged units.', outcome: `${num(Number(result.usable || 0))} usable units found.` };
  if (tool === 'get_demand_evidence') return { title: `Investigated demand${args.lookback_days ? ` over the last ${args.lookback_days} days` : ''}`, reason: 'Determine whether the forecast is credible and whether promotions or stockouts distort recent sales.', outcome: 'Forecast, recent sales and demand signals reviewed.' };
  if (tool === 'get_open_orders') {
    const orders = Array.isArray(result.open_orders) ? result.open_orders.length : 0;
    return { title: 'Reviewed incoming purchase orders', reason: 'Check whether supply is already committed and whether its timing solves the risk.', outcome: `${orders} open order${orders === 1 ? '' : 's'} reviewed.` };
  }
  if (tool === 'get_supplier_options') {
    const options = Array.isArray(result.supplier_options) ? result.supplier_options.length : 0;
    return { title: 'Compared supplier options', reason: 'Find eligible supply, delivery timing, order rules and expedite options.', outcome: `${options} supplier option${options === 1 ? '' : 's'} returned.` };
  }
  if (tool === 'get_constraints') return { title: 'Checked purchasing constraints', reason: 'Verify budget, storage capacity and the boundary for buyer approval.', outcome: 'Hard limits and approval limits retrieved.' };
  if (tool === 'simulate_plan') return describeSimulation(args, result);
  if (tool === 'propose_plan') {
    const disposition = titleCase(String(args.disposition || 'decision'));
    return { title: `Prepared a ${disposition.toLowerCase()} recommendation`, reason: 'The available evidence was sufficient to select and route an action.', outcome: result.approval_required ? 'Recommendation sent to the buyer for approval.' : result.execution ? 'Action passed policy and was executed automatically.' : 'Recommendation recorded.' };
  }
  if (tool === 'ask_buyer') return { title: 'Asked the buyer for missing context', reason: String(args.question || 'A business judgement was required before proceeding.'), outcome: 'Investigation paused for the buyer’s answer.' };
  return { title: titleCase(tool), reason: 'The agent selected this check based on the evidence available at that point.', outcome: 'Step completed.' };
}

function describeSimulation(args: Record<string, unknown>, result: Record<string, unknown>): { title: string; reason: string; outcome: string } {
  const action = String(args.action_type || '');
  const candidate = asRecord(result.candidate);
  if (!action) {
    const candidates = Array.isArray(result.all_candidates) ? result.all_candidates.length : 0;
    return { title: 'Compared available actions', reason: 'Identify which alternatives can close the exposure while respecting cost and operating limits.', outcome: `${candidates} candidate plan${candidates === 1 ? '' : 's'} ranked.` };
  }
  if (action === 'expedite_po') return { title: `Tested expediting ${String(args.po_id || 'an open order')}${args.new_date ? ` to ${dateShort(String(args.new_date))}` : ''}`, reason: 'Check whether moving committed supply earlier resolves the timing gap.', outcome: simulationOutcome(candidate) };
  if (action === 'create_po') return { title: `Tested a ${num(Number(args.qty || 0))}-unit order with ${String(args.supplier_id || 'a supplier')}`, reason: 'Check whether additional supply is feasible and closes the remaining shortage.', outcome: simulationOutcome(candidate) };
  return { title: 'Tested keeping the current plan', reason: 'Confirm whether the case can be resolved without changing a purchase order.', outcome: simulationOutcome(candidate) };
}

function simulationOutcome(candidate: Record<string, unknown>): string {
  if (!Object.keys(candidate).length) return 'Plan simulation completed.';
  if (candidate.feasible === false) {
    const constraints = Array.isArray(candidate.binding_constraints) ? candidate.binding_constraints.join(', ') : 'a hard constraint';
    return `Not feasible because of ${constraints}.`;
  }
  return `${num(Number(candidate.residual_unmet || 0))} units remain unfilled after this plan.`;
}

function ActivityMarker({ state }: { state: Activity['state'] }) {
  const style = state === 'complete' ? 'border-emerald-800 bg-emerald-950/50 text-emerald-300' : state === 'issue' ? 'border-red-800 bg-red-950/50 text-red-300' : 'border-sky-700 bg-sky-950 text-sky-300';
  return <span className={`mt-0.5 flex h-7 w-7 items-center justify-center rounded-full border text-xs font-bold ${style}`} aria-hidden>{state === 'complete' ? '✓' : state === 'issue' ? '!' : <span className="h-2 w-2 animate-pulse rounded-full bg-sky-300" />}</span>;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function eventTime(value: string | null): string {
  if (!value) return '';
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
