// Types mirroring backend/app/api/routes.py response shapes exactly.
// Money fields ending in `_minor` are integer minor units (cents).

export interface CaseListItem {
  case_id: string;
  fixture_id: string | null;
  sku: string;
  node_id: string;
  title: string;
  trigger_type: string;
  recommended_qty: number | null;
  signal_source: string;
  data_as_of: string;
  last_activity_at: string;
  state: string;
  replan_count: number;
  next_actor: string;
  latest_verdict: VerdictKind | null;
  latest_run_mode: 'live' | 'replay' | null;
  projected_unmet_units: number;
  first_stockout_date: string | null;
  latest_disposition: string | null;
  latest_action_type: string | null;
}

export interface CasesResponse {
  cases: CaseListItem[];
}

export type VerdictKind = 'PASS' | 'PARTIAL' | 'FAIL' | 'UNKNOWN';

export interface CaseSummary {
  case_id: string;
  fixture_id: string | null;
  sku: string;
  node_id: string;
  title: string;
  signal_source: string;
  state: string;
  replan_count: number;
  as_of_date: string;
  trigger: { type: string; [key: string]: unknown };
  next_actor: string;
  supplier_behavior: string;
  latest_run_mode: 'live' | 'replay' | null;
}

export interface InventoryEvidence {
  on_hand: number;
  reserved: number;
  quarantine: number;
  damaged: number;
  usable: number;
  snapshot_age_days: number;
  effective_at: string;
}

export interface ProductEvidence { sku: string; name: string; node_id: string }
export interface DemandEvidence {
  horizon_days: number;
  forecast_total_units: number;
  average_daily_units: number;
  safety_stock_units: number;
}

export interface OpenOrderEvidence {
  po_id: string;
  supplier_id: string;
  outstanding_qty: number;
  requested_qty: number;
  confirmed_qty: number;
  received_qty: number;
  cancelled_qty: number;
  requested_date: string;
  confirmed_date: string | null;
  status: string;
  overdue: boolean;
  acknowledged: boolean;
}

export interface BudgetEvidence {
  limit_minor: number | null;
  committed_minor: number | null;
  reserved_minor: number | null;
  available_minor: number | null;
}

export interface CapacityEvidence {
  min_headroom_m3: number;
  unit_volume_m3: number;
}

export interface Evidence {
  product: ProductEvidence;
  inventory: InventoryEvidence;
  demand: DemandEvidence;
  open_orders: OpenOrderEvidence[];
  budget: BudgetEvidence;
  capacity: CapacityEvidence;
  suppliers: SupplierEvidence[];
  unknowns: string[];
}

export interface SupplierEvidence {
  supplier_id: string;
  unit_price_minor: number;
  moq: number;
  pack_size: number;
  lead_time_days: number;
  available_units: number;
  quote_expires_at: string;
  eligible: boolean;
  expedite_available: boolean;
  expedite_fee_minor: number;
  expedite_days_saved: number;
}

export interface CaseOption {
  sku: string;
  node_id: string;
  product_name: string;
  node_name: string;
  as_of_date: string;
  usable_inventory: number;
  forecast_units: number;
  available_budget_minor: number | null;
  storage_headroom_m3: number;
  eligible_suppliers: number;
  projected_unmet_units: number;
}

export interface ProjectionSummary {
  total_demand_units: number;
  total_unmet_units: number;
  first_stockout_date: string | null;
  days_below_safety: number;
  closing_inventory: number;
  peak_occupancy_m3: number;
  has_shortage: boolean;
}

export interface ProjectionDay {
  day: string;
  opening: number;
  receipts: number;
  demand: number;
  served: number;
  unmet: number;
  closing: number;
  below_safety: boolean;
}

export interface Projection {
  summary: ProjectionSummary;
  daily: ProjectionDay[];
}

export interface ConstraintCheckDict {
  name: string;
  passed: boolean;
  binding_reason: string;
  limit: number | null;
  required: number | null;
}

export interface Candidate {
  action_type: string;
  label: string;
  supplier_id: string | null;
  po_id: string | null;
  qty: number | null;
  expected_receipt_date: string | null;
  incremental_cost_minor: number;
  feasible: boolean;
  binding_constraints: string[];
  checks: ConstraintCheckDict[];
  before: ProjectionSummary;
  after: ProjectionSummary;
  unmet_reduction: number;
  residual_unmet: number;
}

export interface Proposal {
  proposal_id: string;
  version: number;
  disposition: string;
  action_type: string;
  action_args: Record<string, unknown>;
  rationale: string;
  important_factors: string[];
  assumptions: string[];
  residual_exposure: Record<string, unknown>;
  simulation: Record<string, unknown>;
  approval_required: boolean;
  approval_reason: string | null;
  state: string;
  decline_reason: string | null;
}

export interface Interaction {
  interaction_id: string;
  kind: string;
  question: string;
  options: string[];
  recommendation: string | null;
  answer: string | null;
}

export interface VerdictCheck {
  layer: 'execution' | 'business' | string;
  name: string;
  passed: boolean;
  detail: string;
}

export interface Verdict {
  verdict: VerdictKind;
  expected: Record<string, unknown>;
  actual: Record<string, unknown>;
  deltas: Record<string, unknown>;
  checks: VerdictCheck[];
  residual_exposure: Record<string, unknown>;
  follow_up: string;
}

export interface ActionItem {
  action_id: string;
  action_type: string;
  state: string;
  po_id: string | null;
  idempotency_key: string;
  attempts: number;
  request: Record<string, unknown>;
  response: Record<string, unknown> | null;
  verdict: Verdict | null;
}

export interface CaseEvent {
  seq: number;
  kind: string;
  label: string;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export interface CaseDetailResponse {
  case: CaseSummary;
  evidence: Evidence;
  projection: Projection;
  candidates: Candidate[];
  proposals: Proposal[];
  interactions: Interaction[];
  actions: ActionItem[];
  events: CaseEvent[];
}

export interface ApiErrorDetail {
  error: string;
  message: string;
  [key: string]: unknown;
}

export interface HealthResponse {
  ok: boolean;
  ai_provider: string;
  ai_model: string;
  llm_key_present: boolean;
  live_agent_available: boolean;
  replay_available: boolean;
}
