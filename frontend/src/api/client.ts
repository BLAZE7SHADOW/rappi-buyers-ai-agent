import type {
  ApiErrorDetail,
  CaseDetailResponse,
  CasesResponse,
} from '../types';

export class ApiError extends Error {
  status: number;
  detail: ApiErrorDetail;

  constructor(status: number, detail: ApiErrorDetail) {
    super(detail.message || `Request failed with status ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers || {}),
      },
    });
  } catch (err) {
    throw new ApiError(0, {
      error: 'NETWORK_ERROR',
      message: 'Could not reach the backend. Is it running on port 8000?',
    });
  }

  if (!res.ok) {
    let detail: ApiErrorDetail = { error: 'UNKNOWN', message: `HTTP ${res.status}` };
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // ignore parse errors, use default detail
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  listCases: () => request<CasesResponse>('/api/cases'),
  getCase: (caseId: string) => request<CaseDetailResponse>(`/api/cases/${encodeURIComponent(caseId)}`),
  runCase: (caseId: string) =>
    request<unknown>(`/api/cases/${encodeURIComponent(caseId)}/run`, { method: 'POST' }),
  postMessage: (caseId: string, text: string) =>
    request<{ ok: boolean }>(`/api/cases/${encodeURIComponent(caseId)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  respondInteraction: (interactionId: string, answer: string) =>
    request<{ ok: boolean; case_id: string }>(
      `/api/interactions/${encodeURIComponent(interactionId)}/respond`,
      { method: 'POST', body: JSON.stringify({ answer }) },
    ),
  approveProposal: (proposalId: string, approver = 'buyer') =>
    request<unknown>(`/api/proposals/${encodeURIComponent(proposalId)}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approver }),
    }),
  declineProposal: (proposalId: string, reason = '') =>
    request<unknown>(`/api/proposals/${encodeURIComponent(proposalId)}/decline`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  executeProposal: (proposalId: string) =>
    request<unknown>(`/api/proposals/${encodeURIComponent(proposalId)}/execute`, {
      method: 'POST',
    }),
  injectDemoEvent: (caseId: string, behavior: string) =>
    request<{ ok: boolean; behavior: string }>('/api/demo/events', {
      method: 'POST',
      body: JSON.stringify({ case_id: caseId, behavior }),
    }),
  resetDemo: () => request<{ ok: boolean; note: string }>('/api/demo/reset', { method: 'POST' }),
};
