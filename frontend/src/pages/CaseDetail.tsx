import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { AgentProgress } from '../components/AgentProgress';
import { StateBadge } from '../components/Badges';
import { CandidatesTable } from '../components/CandidatesTable';
import { ControlsBar } from '../components/ControlsBar';
import { EvidencePanel } from '../components/EvidencePanel';
import { ProjectionChart } from '../components/ProjectionChart';
import { ProposalCard } from '../components/ProposalCard';
import { QuestionCard } from '../components/QuestionCard';
import { ErrorBanner, Spinner } from '../components/StatusViews';
import { Timeline } from '../components/Timeline';
import { VerdictPanel } from '../components/VerdictPanel';
import { WorkflowStepper } from '../components/WorkflowStepper';
import { dateShort, money, num, titleCase } from '../format';
import type { Candidate, CaseDetailResponse, Evidence, HealthResponse, Projection, Proposal } from '../types';

export function CaseDetail() {
  const { caseId = '' } = useParams();
  const [data, setData] = useState<CaseDetailResponse | null>(null);
  const [loadFailure, setLoadFailure] = useState<{ caseId: string; error: unknown } | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [mutationError, setMutationError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [health, setHealth] = useState<HealthResponse | null>(null);

  const load = useCallback(() => api.getCase(caseId)
    .then((response) => {
      setData(response);
      setLoadFailure(null);
    })
    .catch((error) => setLoadFailure({ caseId, error })), [caseId]);

  useEffect(() => {
    api.getCase(caseId)
      .then((response) => {
        setData(response);
        setLoadFailure(null);
      })
      .catch((error) => setLoadFailure({ caseId, error }))
      .finally(() => setLoading(false));
    api.health().then(setHealth).catch(() => setHealth(null));
  }, [caseId]);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => { void load(); }, 700);
    return () => window.clearInterval(timer);
  }, [load, running]);

  const runAgent = async (mode: 'live' | 'replay') => {
    setRunning(true);
    setMutationError(null);
    try {
      await api.runCase(caseId, mode);
      await load();
    } catch (error) {
      setMutationError(error);
    } finally {
      setRunning(false);
    }
  };

  const resetDemo = async () => {
    setBusy(true);
    setMutationError(null);
    try {
      await api.resetDemo();
      await load();
    } catch (error) {
      setMutationError(error);
    } finally {
      setBusy(false);
    }
  };

  const injectBehavior = async (behavior: string) => {
    setMutationError(null);
    try {
      await api.injectDemoEvent(caseId, behavior);
      await load();
    } catch (error) {
      setMutationError(error);
    }
  };

  const respondInteraction = async (interactionId: string, answer: string) => {
    setBusy(true);
    setMutationError(null);
    try {
      await api.respondInteraction(interactionId, answer);
      await load();
    } catch (error) {
      setMutationError(error);
    } finally {
      setBusy(false);
    }
  };

  const approveProposal = async (proposalId: string) => {
    setBusy(true);
    setMutationError(null);
    try {
      await api.approveProposal(proposalId);
      await load();
    } catch (error) {
      setMutationError(error);
    } finally {
      setBusy(false);
    }
  };

  const declineProposal = async (proposalId: string, reason: string) => {
    setBusy(true);
    setMutationError(null);
    try {
      await api.declineProposal(proposalId, reason);
      await load();
    } catch (error) {
      setMutationError(error);
    } finally {
      setBusy(false);
    }
  };

  const activeError = loadFailure?.caseId === caseId ? loadFailure.error : null;
  if (loading || (!activeError && data?.case.case_id !== caseId)) {
    return <div className="mx-auto max-w-6xl p-6"><Spinner label="Loading case…" /></div>;
  }
  if (activeError || !data) {
    return (
      <div className="mx-auto max-w-6xl p-6">
        <Link to="/" className="mb-4 inline-block text-sm text-sky-400 hover:underline">← Back to inbox</Link>
        <ErrorBanner error={activeError} />
      </div>
    );
  }

  const { case: currentCase, evidence, projection, candidates, proposals, interactions, actions, events } = data;
  const recommendedQty = currentCase.trigger.recommended_qty as number | undefined;
  const pendingInteractions = interactions.filter((interaction) => interaction.answer === null);
  const latestProposal = proposals.at(-1);
  const canRun = ['investigating', 'pending_investigation', 'reopened'].includes(currentCase.state);
  const confirmedIncoming = evidence.open_orders
    .filter((order) => order.acknowledged && !order.overdue)
    .reduce((total, order) => total + order.outstanding_qty, 0);
  const nextConfirmedOrder = evidence.open_orders
    .filter((order) => order.acknowledged && !order.overdue && order.confirmed_date)
    .sort((a, b) => String(a.confirmed_date).localeCompare(String(b.confirmed_date)))[0];
  const supplyVolume = evidence.inventory.usable + confirmedIncoming;
  const volumeBalance = supplyVolume - projection.summary.total_demand_units;
  const deliveryGapDays = projection.summary.first_stockout_date && nextConfirmedOrder?.confirmed_date
    ? daysBetween(projection.summary.first_stockout_date, nextConfirmedOrder.confirmed_date)
    : null;
  const recommendationCandidates = recommendedQty == null
    ? []
    : candidates.filter((candidate) => candidate.action_type === 'create_po' && candidate.qty === recommendedQty);
  const controls = (
    <ControlsBar
      running={running}
      onRun={runAgent}
      onReset={resetDemo}
      onInjectBehavior={injectBehavior}
      currentBehavior={currentCase.supplier_behavior}
      canRun={canRun}
      liveAvailable={health?.live_agent_available ?? false}
      replayAvailable={(health?.replay_available ?? true) && currentCase.fixture_id !== null}
      nextActor={titleCase(currentCase.next_actor)}
    />
  );

  return (
    <div className="mx-auto max-w-7xl space-y-7 p-4 sm:p-6">
      <Link to="/" className="inline-block text-sm text-sky-400 hover:underline">← Back to exception queue</Link>

      <header className="rounded-2xl border border-gray-800 bg-gradient-to-br from-gray-950 to-slate-950 p-5 shadow-xl shadow-black/20 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-400">Purchasing decision · {currentCase.case_id}</p>
            <h1 className="mt-1 text-2xl font-semibold text-gray-100">{evidence.product.name}</h1>
            <p className="mt-1 text-sm text-gray-500">{currentCase.sku} · {currentCase.node_id} · Evidence as of {dateShort(currentCase.as_of_date)} · Source: {currentCase.signal_source}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StateBadge state={currentCase.state} />
            <span className="rounded-full border border-gray-700 px-2.5 py-1 text-xs text-gray-400">Owner: {titleCase(currentCase.next_actor)}</span>
            {currentCase.latest_run_mode && <span className="rounded-full border border-gray-700 px-2.5 py-1 text-xs text-gray-400">{titleCase(currentCase.latest_run_mode)} run</span>}
          </div>
        </div>
        <div className="mt-5"><WorkflowStepper state={currentCase.state} /></div>
      </header>

      {!!mutationError && <ErrorBanner error={mutationError} />}
      {pendingInteractions.map((interaction) => (
        <QuestionCard key={interaction.interaction_id} interaction={interaction} busy={busy} onRespond={(answer) => respondInteraction(interaction.interaction_id, answer)} />
      ))}

      <DecisionBrief recommendedQty={recommendedQty} triggerType={String(currentCase.trigger.type)} projection={projection} latestProposal={latestProposal} caseState={currentCase.state} />
      {canRun && controls}

      <AgentProgress events={events} running={running} />

      {latestProposal && (
        <Section id="buyer-decision" eyebrow="Recommended action" title={latestProposal.approval_required && currentCase.state === 'awaiting_approval' ? 'Buyer decision required' : 'Agent decision'}>
          <ProposalCard proposal={latestProposal} caseState={currentCase.state} busy={busy} onApprove={() => approveProposal(latestProposal.proposal_id)} onDecline={(reason) => declineProposal(latestProposal.proposal_id, reason)} />
        </Section>
      )}

      <Section eyebrow="Why this case needs attention" title="The supply picture">
        <div className="grid items-stretch gap-3 lg:grid-cols-3">
          <CalculationPanel
            step="1"
            title="Inventory available today"
            subtitle="Exclude stock that cannot be sold"
            rows={[
              { label: 'On hand', value: num(evidence.inventory.on_hand) },
              { label: 'Reserved', value: `− ${num(evidence.inventory.reserved)}` },
              { label: 'Quarantine', value: `− ${num(evidence.inventory.quarantine)}` },
              { label: 'Damaged', value: `− ${num(evidence.inventory.damaged)}` },
            ]}
            resultLabel="Usable now"
            resultValue={`${num(evidence.inventory.usable)} units`}
          />
          <CalculationPanel
            step="2"
            title={`${evidence.demand.horizon_days}-day volume balance`}
            subtitle="Enough total units, regardless of arrival timing"
            rows={[
              { label: 'Usable today', value: num(evidence.inventory.usable) },
              { label: `Confirmed ${nextConfirmedOrder?.po_id || 'PO'}`, value: `+ ${num(confirmedIncoming)}` },
              { label: 'Forecast demand', value: `− ${num(projection.summary.total_demand_units)}` },
            ]}
            resultLabel="Total volume balance"
            resultValue={`${volumeBalance >= 0 ? '+' : '−'}${num(Math.abs(volumeBalance))} units`}
            tone={volumeBalance >= 0 ? 'good' : 'warn'}
          />
          <CalculationPanel
            step="3"
            title="Delivery timing gap"
            subtitle="Incoming stock is unavailable until its arrival date"
            rows={[
              { label: 'Inventory runs out', value: dateShort(projection.summary.first_stockout_date) },
              { label: `${nextConfirmedOrder?.po_id || 'Next PO'} arrives`, value: dateShort(nextConfirmedOrder?.confirmed_date) },
              { label: 'Days without stock', value: deliveryGapDays == null ? '—' : `${deliveryGapDays} days` },
              { label: 'Forecast per day', value: `${num(evidence.demand.average_daily_units)} units` },
            ]}
            resultLabel={deliveryGapDays == null ? 'Projected shortage' : `${deliveryGapDays} days × ${num(evidence.demand.average_daily_units)} units/day`}
            resultValue={`${num(projection.summary.total_unmet_units)} units unfilled`}
            tone={projection.summary.total_unmet_units > 0 ? 'warn' : 'good'}
          />
        </div>
      </Section>

      {!latestProposal && <Section eyebrow="Policy and feasibility" title="Constraints to check"><ConstraintSummary evidence={evidence} candidates={recommendationCandidates} recommendedQty={recommendedQty} /></Section>}

      {actions.length > 0 && <Section eyebrow="Feedback loop" title="Did the action actually work?"><VerdictPanel actions={actions} /></Section>}

      <Section eyebrow="Demand and supply over time" title={`${evidence.demand.horizon_days}-day outlook`}>
        <ProjectionChart daily={projection.daily} safetyStock={evidence.demand.safety_stock_units} />
      </Section>

      <div className="space-y-3">
        <Disclosure title="Operational evidence" summary="Inventory, demand, open purchase orders, budget, storage, and supplier terms"><EvidencePanel evidence={evidence} /></Disclosure>
        <Disclosure title="Alternatives compared" summary={`${candidates.length} plans simulated, including infeasible options and why they were rejected`}><CandidatesTable candidates={candidates} /></Disclosure>
        {proposals.length > 1 && (
          <Disclosure title="Earlier decisions" summary={`${proposals.length - 1} previous proposal${proposals.length === 2 ? '' : 's'} retained for audit`}>
            <div className="space-y-3">{proposals.slice(0, -1).map((proposal) => <ProposalCard key={proposal.proposal_id} proposal={proposal} caseState={currentCase.state} busy={busy} onApprove={() => approveProposal(proposal.proposal_id)} onDecline={(reason) => declineProposal(proposal.proposal_id, reason)} />)}</div>
          </Disclosure>
        )}
        <Disclosure title="Technical audit log" summary={`${events.length} immutable system events for debugging and compliance`}><Timeline events={events} /></Disclosure>
        {!canRun && <Disclosure title="Demo controls" summary="Change the simulated supplier response or reset all fixtures">{controls}</Disclosure>}
      </div>

      <footer className="border-t border-gray-800 pt-4 text-xs leading-5 text-gray-600">Model assumptions: daily resolution; receipts arrive before that day's demand; unmet demand is lost rather than backlogged. Money uses integer minor units. Available budget: {money(evidence.budget.available_minor)}.</footer>
    </div>
  );
}

function CalculationPanel({ step, title, subtitle, rows, resultLabel, resultValue, tone = 'neutral' }: { step: string; title: string; subtitle: string; rows: { label: string; value: string }[]; resultLabel: string; resultValue: string; tone?: 'neutral' | 'warn' | 'good' }) {
  const resultClass = tone === 'warn' ? 'text-amber-300' : tone === 'good' ? 'text-emerald-300' : 'text-gray-100';
  return (
    <div className="flex h-full min-h-72 flex-col rounded-xl border border-gray-800 bg-gray-950 p-5">
      <div className="flex items-start gap-3">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-sky-800 bg-sky-950/50 text-xs font-semibold text-sky-300">{step}</span>
        <div><h3 className="font-semibold text-gray-100">{title}</h3><p className="mt-0.5 text-xs leading-5 text-gray-500">{subtitle}</p></div>
      </div>
      <dl className="mt-5 flex-1 space-y-2.5 text-sm">
        {rows.map((row) => <div key={row.label} className="grid grid-cols-[1fr_auto] items-baseline gap-4"><dt className="text-gray-500">{row.label}</dt><dd className="text-right font-mono tabular-nums text-gray-200">{row.value}</dd></div>)}
      </dl>
      <div className="mt-4 border-t border-gray-700 pt-4">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">{resultLabel}</p>
        <p className={`mt-1 text-xl font-semibold tabular-nums ${resultClass}`}>{resultValue}</p>
      </div>
    </div>
  );
}

function Section({ title, eyebrow, children, id }: { title: string; eyebrow?: string; children: React.ReactNode; id?: string }) {
  return <section id={id} className="scroll-mt-4">{eyebrow && <p className="text-xs font-semibold uppercase tracking-[0.16em] text-sky-500">{eyebrow}</p>}<h2 className="mb-3 mt-1 text-xl font-semibold text-gray-100">{title}</h2>{children}</section>;
}

function DecisionBrief({ recommendedQty, triggerType, projection, latestProposal, caseState }: { recommendedQty?: number; triggerType: string; projection: Projection; latestProposal?: Proposal; caseState: string }) {
  const decisionReady = !!latestProposal;
  const needsApproval = !!latestProposal?.approval_required && caseState === 'awaiting_approval';
  return (
    <section className={`overflow-hidden rounded-2xl border ${needsApproval ? 'border-amber-700/70 bg-amber-950/15' : 'border-sky-900/70 bg-sky-950/15'}`}>
      <div className="grid lg:grid-cols-[1.4fr_.6fr]">
        <div className="p-5 sm:p-6">
          <p className={`text-xs font-semibold uppercase tracking-[0.18em] ${needsApproval ? 'text-amber-300' : 'text-sky-300'}`}>{needsApproval ? 'Buyer decision needed' : decisionReady ? 'Decision brief' : 'Agent review needed'}</p>
          <h2 className="mt-2 text-2xl font-semibold leading-tight text-white">{decisionReady ? `${titleCase(latestProposal.disposition)} the incoming recommendation; ${titleCase(latestProposal.action_type)}` : projection.summary.total_unmet_units > 0 ? `${num(projection.summary.total_unmet_units)} units of demand may go unfilled` : 'The current supply plan covers forecast demand'}</h2>
          <p className="mt-3 text-sm text-gray-300">{decisionReady ? 'The evidence, constraints and proposed action are ready below.' : `Review the ${num(recommendedQty)}-unit ${titleCase(triggerType)} signal before any purchase is made.`}</p>
        </div>
        <div className="border-t border-gray-800 bg-black/20 p-5 lg:border-l lg:border-t-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">What happens next</p>
          <p className="mt-2 text-base font-semibold text-gray-100">{needsApproval ? 'Review the recommendation and approve or decline it.' : decisionReady ? workflowInstruction(caseState) : 'Run the agent to investigate and compare feasible actions.'}</p>
          {needsApproval && <a href="#buyer-decision" className="mt-4 inline-flex rounded-lg bg-amber-400 px-4 py-2.5 text-sm font-bold text-gray-950 shadow-lg shadow-amber-950/40 hover:bg-amber-300">Review and decide ↓</a>}
        </div>
      </div>
    </section>
  );
}

function ConstraintSummary({ evidence, candidates, recommendedQty }: { evidence: Evidence; candidates: Candidate[]; recommendedQty?: number }) {
  const capacityUnits = evidence.capacity.unit_volume_m3 > 0 ? Math.floor(evidence.capacity.min_headroom_m3 / evidence.capacity.unit_volume_m3) : null;
  const failed = candidates.flatMap((candidate) => candidate.checks.filter((check) => !check.passed));
  return (
    <div className="space-y-3">
      {recommendedQty != null && candidates.length > 0 && <div className={`rounded-xl border p-4 ${failed.length ? 'border-red-900/70 bg-red-950/15' : 'border-emerald-900/70 bg-emerald-950/15'}`}><p className={`font-semibold ${failed.length ? 'text-red-200' : 'text-emerald-200'}`}>Incoming {num(recommendedQty)}-unit recommendation: {failed.length ? 'not executable as submitted' : 'feasible with at least one supplier'}</p><p className="mt-1 text-sm leading-6 text-gray-400">{failed.length ? Array.from(new Set(failed.map((check) => check.binding_reason))).join(' ') : 'All hard constraints pass for at least one simulated supplier plan.'}</p></div>}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Guardrail icon="$" label="Budget" value={money(evidence.budget.available_minor)} detail="Available this planning period" good={evidence.budget.available_minor !== null && evidence.budget.available_minor > 0} />
        <Guardrail icon="▣" label="Storage" value={capacityUnits == null ? 'Unknown' : `${num(capacityUnits)} units`} detail={`${num(evidence.capacity.min_headroom_m3)} m³ minimum headroom`} good={capacityUnits !== null && capacityUnits > 0} />
        <Guardrail icon="S" label="Suppliers" value={`${evidence.suppliers.filter((supplier) => supplier.eligible).length} eligible`} detail="MOQ, pack, availability, lead time and quote checked" good={evidence.suppliers.some((supplier) => supplier.eligible)} />
        <Guardrail icon="✓" label="Evidence" value={evidence.unknowns.length === 0 ? 'Complete' : `${evidence.unknowns.length} gap${evidence.unknowns.length === 1 ? '' : 's'}`} detail={evidence.unknowns.length === 0 ? 'No decision-critical facts missing' : evidence.unknowns.join(', ')} good={evidence.unknowns.length === 0} />
      </div>
    </div>
  );
}

function Guardrail({ icon, label, value, detail, good }: { icon: string; label: string; value: string; detail: string; good: boolean }) {
  return <div className="rounded-xl border border-gray-800 bg-gray-950 p-4"><div className="flex items-center justify-between"><span className="flex h-7 w-7 items-center justify-center rounded-md bg-gray-900 text-xs text-sky-300">{icon}</span><span className={good ? 'text-emerald-400' : 'text-red-400'}>{good ? '✓' : '!'}</span></div><p className="mt-3 text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</p><p className="mt-1 text-lg font-semibold text-gray-100">{value}</p><p className="mt-1 text-xs leading-5 text-gray-500">{detail}</p></div>;
}

function Disclosure({ title, summary, children }: { title: string; summary: string; children: React.ReactNode }) {
  return <details className="group rounded-xl border border-gray-800 bg-gray-950/60"><summary className="flex cursor-pointer list-none items-center gap-4 p-4 hover:bg-gray-900/60"><span className="flex h-8 w-8 items-center justify-center rounded-lg border border-gray-700 text-gray-400 group-open:text-sky-300">＋</span><span className="flex-1"><span className="block font-semibold text-gray-200">{title}</span><span className="mt-0.5 block text-xs text-gray-500">{summary}</span></span><span className="text-xs text-gray-600 transition group-open:rotate-180">▼</span></summary><div className="border-t border-gray-800 p-4">{children}</div></details>;
}

function workflowInstruction(state: string): string {
  if (state === 'resolved') return 'The action passed validation and the case is resolved.';
  if (state === 'reopened') return 'The outcome differed from plan; run the agent again to replan.';
  if (state === 'escalated') return 'A human must resolve the constraint before purchasing can continue.';
  if (state === 'awaiting_confirmation') return 'Waiting for the supplier to confirm the order.';
  return `The workflow is ${titleCase(state)}.`;
}

function daysBetween(startIso: string, endIso: string): number {
  return Math.round((new Date(`${endIso}T00:00:00`).getTime() - new Date(`${startIso}T00:00:00`).getTime()) / 86_400_000);
}
