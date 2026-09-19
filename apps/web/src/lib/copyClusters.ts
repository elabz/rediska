/**
 * Post copy detection client helpers (mirrors services/core copy_clusters API).
 *
 * All calls go through the /api/core/copy-clusters BFF proxies.
 */

import { errorMessage } from '@/lib/banList';

export type CopyKind = 'ring_suspect' | 'returning_author' | 'unclassified';
export type CopyDecision = 'confirmed_ring' | 'same_person' | 'coincidence';
/** The effective kind: the human decision when there is one, else the computed kind. */
export type EffectiveCopyKind = CopyKind | CopyDecision;

/** The `copy` field carried by leads, scout posts and needs-review items. */
export interface CopyInfo {
  cluster_id: number;
  kind: EffectiveCopyKind;
  computed_kind: CopyKind;
  decision: CopyDecision | null;
  author_count: number;
  /** Spam ring handled automatically: skipped by the scout, hidden from lists. */
  handled?: boolean;
  earliest_other_posted_at: string | null;
}

export interface CopyClusterSummary {
  id: number;
  provider_id: string;
  kind: EffectiveCopyKind;
  computed_kind: CopyKind;
  decision: CopyDecision | null;
  decision_notes: string | null;
  decided_at: string | null;
  author_count: number;
  member_count: number;
  avg_char_len?: number;
  handled?: boolean;
  first_posted_at: string | null;
  last_posted_at: string | null;
  created_at: string;
}

export interface CopyClusterMember {
  member_id: number;
  fingerprint_id: number;
  external_post_id: string;
  author_username: string | null;
  account_id: number | null;
  remote_status: string | null;
  posted_at: string | null;
  first_seen_at: string;
  location: string | null;
  source: string;
  char_len: number;
  similarity: number | null;
  repost_of_id: number | null;
  lead_id: number | null;
  lead_status: string | null;
  scout_post_id: number | null;
  scout_watch_id: number | null;
  analysis_id: number | null;
  recommendation: string | null;
  human_verdict: string | null;
  ban_id: number | null;
  ban_status: string | null;
}

export interface CopyClusterDetail {
  cluster: CopyClusterSummary;
  members: CopyClusterMember[];
}

export interface CopyClusterListResponse {
  items: CopyClusterSummary[];
  next_cursor: string | null;
}

export const KIND_LABELS: Record<EffectiveCopyKind, string> = {
  ring_suspect: 'Ring suspect',
  returning_author: 'Returning author',
  unclassified: 'Unclassified',
  confirmed_ring: 'Confirmed ring',
  same_person: 'Same person',
  coincidence: 'Coincidence',
};

export const KIND_DESCRIPTIONS: Record<EffectiveCopyKind, string> = {
  ring_suspect: 'Live accounts posting the same text close together, or three or more authors',
  returning_author: 'An earlier account went quiet or was deleted, then this text came back',
  unclassified: 'Copied text whose timing does not settle what it is',
  confirmed_ring: 'You confirmed these accounts are a ring',
  same_person: 'You judged these accounts to be one person',
  coincidence: 'You marked this as a template or quote; it no longer clusters',
};

/** Badge colours per effective kind. */
export const KIND_STYLE: Record<EffectiveCopyKind, string> = {
  ring_suspect: 'bg-red-500/10 text-red-700 border-red-500/30 dark:text-red-300',
  confirmed_ring: 'bg-red-500/15 text-red-800 border-red-500/50 dark:text-red-200',
  returning_author: 'bg-sky-500/10 text-sky-700 border-sky-500/30 dark:text-sky-300',
  same_person: 'bg-sky-500/15 text-sky-800 border-sky-500/50 dark:text-sky-200',
  unclassified: 'bg-amber-500/10 text-amber-700 border-amber-500/30 dark:text-amber-300',
  coincidence: 'bg-muted text-muted-foreground border-border',
};

export const DECISION_OPTIONS: { value: CopyDecision; label: string }[] = [
  { value: 'confirmed_ring', label: 'Confirmed ring' },
  { value: 'same_person', label: 'Same person' },
  { value: 'coincidence', label: 'Coincidence' },
];

export function kindLabel(kind: string | null | undefined): string {
  if (!kind) return '—';
  return (KIND_LABELS as Record<string, string>)[kind] ?? kind;
}

export function kindStyle(kind: string | null | undefined): string {
  return (KIND_STYLE as Record<string, string>)[kind ?? ''] ?? KIND_STYLE.unclassified;
}

/** Core returns naive UTC timestamps. */
export function toUtc(dateString: string): string {
  return /[zZ]|[+-]\d\d:\d\d$/.test(dateString) ? dateString : `${dateString}Z`;
}

export function formatDay(dateString: string | null | undefined): string {
  if (!dateString) return '—';
  return new Date(toUtc(dateString)).toLocaleDateString('en-US', {
    timeZone: 'America/New_York',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
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

export function fetchCopyClusters(params: {
  kind?: string;
  decision?: string;
  author?: string;
  handled?: boolean;
  cursor?: string | null;
  limit?: number;
}) {
  const qs = new URLSearchParams();
  if (params.kind) qs.set('kind', params.kind);
  if (params.decision) qs.set('decision', params.decision);
  if (params.author) qs.set('author', params.author);
  if (params.handled !== undefined) qs.set('handled', String(params.handled));
  if (params.cursor) qs.set('cursor', params.cursor);
  qs.set('limit', String(params.limit ?? 25));
  return request<CopyClusterListResponse>(`/api/core/copy-clusters?${qs.toString()}`);
}

export function fetchCopyCluster(clusterId: number) {
  return request<CopyClusterDetail>(`/api/core/copy-clusters/${clusterId}`);
}

export function decideCopyCluster(
  clusterId: number,
  decision: CopyDecision | null,
  notes?: string | null,
) {
  return request<CopyClusterSummary>(`/api/core/copy-clusters/${clusterId}/decision`, {
    method: 'POST',
    body: JSON.stringify({ decision, notes: notes || null }),
  });
}
