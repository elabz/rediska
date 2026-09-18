/**
 * Contact ban list client helpers (mirrors services/core ban_list API).
 *
 * All calls go through the /api/core/ban-list BFF proxies.
 */

export type BanSource = 'manual' | 'copy_ring' | 'import';
export type BanStatus = 'active' | 'lifted';

export interface BanEntry {
  id: number;
  provider_id: string;
  username: string;
  reason: string | null;
  notes: string | null;
  source: BanSource;
  status: BanStatus;
  cluster_id: number | null;
  created_by: string | null;
  created_at: string;
  lifted_at: string | null;
  account_id: number | null;
  lead_ids: number[];
}

export interface BanStatusResponse {
  banned: boolean;
  entry: BanEntry | null;
}

export interface BanListResponse {
  items: BanEntry[];
  next_cursor: string | null;
}

export interface BanCreateResponse {
  entry: BanEntry;
  created: boolean;
  reactivated: boolean;
  leads_withdrawn: number[];
}

export interface BanLiftResponse {
  entry: BanEntry;
  leads_restored: number[];
}

export interface SuggestionAuthor {
  username: string;
  account_id: number | null;
  remote_status: string | null;
  first_posted_at: string | null;
  post_count: number;
  banned: boolean;
  dismissed: boolean;
  earliest: boolean;
}

export interface BanSuggestion {
  cluster_id: number;
  kind: string;
  authors: SuggestionAuthor[];
  suggested_usernames: string[];
}

export interface BanSuggestionsResponse {
  available: boolean;
  items: BanSuggestion[];
}

/** Reason presets; `other` needs notes to be useful but any reason is accepted. */
export const REASON_PRESETS = [
  'scam',
  'copy_ring',
  'hostile',
  'asked_not_to_contact',
  'other',
] as const;
export type ReasonPreset = (typeof REASON_PRESETS)[number];

export const REASON_LABELS: Record<ReasonPreset, string> = {
  scam: 'Scam / seller',
  copy_ring: 'Copy ring',
  hostile: 'Hostile',
  asked_not_to_contact: 'Asked not to be contacted',
  other: 'Other',
};

export const SOURCE_LABELS: Record<BanSource, string> = {
  manual: 'Manual',
  copy_ring: 'Copy ring',
  import: 'Import',
};

export const COUNTERPART_BANNED = 'counterpart_banned';

export function reasonLabel(reason: string | null | undefined): string {
  if (!reason) return '—';
  return (REASON_LABELS as Record<string, string>)[reason] ?? reason;
}

export function normalizeUsername(username: string): string {
  return username.trim().replace(/^\/?u\//i, '').trim();
}

/** The 409 detail body for a banned counterpart, or null for any other error. */
export function bannedDetail(
  body: unknown,
): { code: string; message: string; username: string; ban_id: number | null } | null {
  if (!body || typeof body !== 'object') return null;
  const detail = (body as { detail?: unknown }).detail;
  if (
    detail &&
    typeof detail === 'object' &&
    (detail as { code?: unknown }).code === COUNTERPART_BANNED
  ) {
    return detail as { code: string; message: string; username: string; ban_id: number | null };
  }
  return null;
}

/** Human-readable message from an API error body (string or structured detail). */
export function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === 'object') {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object' && 'message' in detail) {
      return String((detail as { message: unknown }).message);
    }
  }
  return fallback;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(errorMessage(body, `Request failed (${response.status})`));
  }
  return body as T;
}

export function fetchBanStatus(username: string, providerId = 'reddit') {
  const params = new URLSearchParams({ username, provider_id: providerId });
  return request<BanStatusResponse>(`/api/core/ban-list/status?${params.toString()}`);
}

export function fetchBanList(params: {
  status?: BanStatus | '';
  source?: BanSource | '';
  q?: string;
  cursor?: string | null;
  limit?: number;
}) {
  const qs = new URLSearchParams();
  if (params.status) qs.set('status', params.status);
  if (params.source) qs.set('source', params.source);
  if (params.q?.trim()) qs.set('q', params.q.trim());
  if (params.cursor) qs.set('cursor', params.cursor);
  qs.set('limit', String(params.limit ?? 50));
  return request<BanListResponse>(`/api/core/ban-list?${qs.toString()}`);
}

export function createBan(payload: {
  username: string;
  reason: string;
  notes?: string | null;
  provider_id?: string;
}) {
  return request<BanCreateResponse>('/api/core/ban-list', {
    method: 'POST',
    body: JSON.stringify({ provider_id: 'reddit', ...payload }),
  });
}

export function liftBan(banId: number, notes?: string) {
  return request<BanLiftResponse>(`/api/core/ban-list/${banId}/lift`, {
    method: 'POST',
    body: JSON.stringify(notes ? { notes } : {}),
  });
}

export function bulkBan(payload: {
  cluster_id?: number | null;
  usernames?: string[];
  reason: string;
  notes?: string | null;
  exclude_usernames?: string[];
}) {
  return request<{ cluster_id: number | null; banned: BanCreateResponse[] }>(
    '/api/core/ban-list/bulk',
    { method: 'POST', body: JSON.stringify({ provider_id: 'reddit', ...payload }) },
  );
}

export function fetchBanSuggestions() {
  return request<BanSuggestionsResponse>('/api/core/ban-list/suggestions');
}

export function dismissBanSuggestion(clusterId: number, username: string) {
  return request<{ members: number }>('/api/core/ban-list/suggestions/dismiss', {
    method: 'POST',
    body: JSON.stringify({ cluster_id: clusterId, username }),
  });
}
