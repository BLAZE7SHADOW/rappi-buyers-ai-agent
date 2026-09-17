import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ApiError } from '../api/client';
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
import { money, num, titleCase } from '../format';
import type { CaseDetailResponse } from '../types';

export function CaseDetail() {
  const { caseId = '' } = useParams();
  const [data, setData] = useState<CaseDetailResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [mutationError, setMutationError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setError(null);
    return api
      .getCase(caseId)
      .then((res) => setData(res))
      .catch((err) => setError(err));
  }, [caseId]);

  useEffect(() => {
    setLoading(true);
    load().finally(() => setLoading(false));
  }, [load]);

  const runAgent = async () => {
    setRunning(true);
    setMutationError(null);
    try {
      await api.runCase(caseId);
      await load();
    } catch (err) {
      setMutationError(err);
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
    } catch (err) {
      setMutationError(err);
    } finally {
      setBusy(false);
    }
  };

  const injectBehavior = async (behavior: string) => {
    setMutationError(null);
    try {
      await api.injectDemoEvent(caseId, behavior);
      await load();
    } catch (err) {
      setMutationError(err);
    }
  };

  const respondInteraction = async (interactionId: string, answer: string) => {
    setBusy(true);
    setMutationError(null);
    try {
      await api.respondInteraction(interactionId, answer);
      await load();
    } catch (err) {
      setMutationError(err);
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
    } catch (err) {
      setMutationError(err);
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
    } catch (err) {
      setMutationError(err);
    } finally {
      setBusy(false);
    }
  };

  const executeProposal = async (proposalId: string) => {
    setBusy(true);
    setMutationError(null);
    try {
      await api.executeProposal(proposalId);
      await load();
    } catch (err) {
      setMutationError(err);
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="mx-auto max-w-6xl p-6">
        <Spinner label="Loading case…" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="mx-auto max-w-6xl p-6">
        <Link to="/" className="mb-4 inline-block text-sm text-sky-400 hover:underline">
          ← Back to inbox
        </Link>
        <ErrorBanner error={error} />
      </div>
    );
  }

  const { case: c, evidence, projection, candidates, proposals, interactions, actions, events } = data;
  const trigger = c.trigger;
  const recommendedQty = trigger.recommended_qty as number | undefined;
  const pendingInteractions = interactions.filter((i) => i.answer === null);

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div>
        <Link to="/" className="text-sm text-sky-400 hover:underline">
          ← Back to inbox
        </Link>
      </div>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">{c.title}</h1>
          <p className="mt-1 text-sm text-gray-500">
            {c.fixture_id} · {c.sku} / {c.node_id} · as of {c.as_of_date}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StateBadge state={c.state} />
          <span className="text-sm text-gray-400">Next actor: {titleCase(c.next_actor)}</span>
        </div>
      </div>

      {!!mutationError && <ErrorBanner error={mutationError} />}

      <ControlsBar
        running={running}
        onRun={runAgent}
        onReset={resetDemo}
        onInjectBehavior={injectBehavior}
        currentBehavior={c.supplier_behavior}
      />

      {pendingInteractions.map((i) => (
        <QuestionCard key={i.interaction_id} interaction={i} busy={busy} onRespond={(answer) => respondInteraction(i.interaction_id, answer)} />
      ))}

      {/* a) Situation */}
      <Section title="Situation">
        <p className="text-sm text-gray-200">
          {titleCase(trigger.type as string)}
          {recommendedQty != null ? `: system recommends buying ${num(recommendedQty)} units` : ''}.
        </p>
        <p className="mt-1 text-sm text-gray-400">
          Current exposure: {num(projection.summary.total_unmet_units)} units unmet
          {projection.summary.first_stockout_date ? `, first stockout ${projection.summary.first_stockout_date}` : ', no projected stockout'}.
        </p>
      </Section>

      {/* b) Evidence */}
      <Section title="Evidence">
        <EvidencePanel evidence={evidence} />
      </Section>

      {/* c) Projection */}
      <Section title="Projection (28-day horizon)">
        <ProjectionChart daily={projection.daily} />
        <p className="mt-2 text-xs text-gray-500">
          Total demand {num(projection.summary.total_demand_units)} · Unmet {num(projection.summary.total_unmet_units)} ·
          Days below safety stock {projection.summary.days_below_safety} · Peak occupancy {projection.summary.peak_occupancy_m3} m³
        </p>
      </Section>

      {/* d) Plan comparison */}
      <Section title="Plan comparison">
        <CandidatesTable candidates={candidates} />
      </Section>

      {/* e) Verdict */}
      <Section title="Verdict">
        <VerdictPanel actions={actions} />
      </Section>

      {/* Proposals */}
      <Section title="Proposals">
        {proposals.length === 0 ? (
          <p className="text-sm text-gray-500">No proposals yet.</p>
        ) : (
          <div className="space-y-3">
            {proposals.map((p) => (
              <ProposalCard
                key={p.proposal_id}
                proposal={p}
                caseState={c.state}
                busy={busy}
                onApprove={() => approveProposal(p.proposal_id)}
                onDecline={(reason) => declineProposal(p.proposal_id, reason)}
                onExecute={() => executeProposal(p.proposal_id)}
              />
            ))}
          </div>
        )}
      </Section>

      {/* Timeline */}
      <Section title="Investigation timeline">
        <Timeline events={events} />
      </Section>

      <footer className="border-t border-gray-800 pt-4 text-xs text-gray-600">
        Model assumptions: daily resolution (intraday stockouts are out of scope); receipts arrive before that
        day's demand; unmet demand is lost, not backlogged. Money values shown here are derived from integer minor
        units, e.g. budget available is {money(evidence.budget.available_minor)}.
      </footer>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-400">{title}</h2>
      {children}
    </section>
  );
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}
