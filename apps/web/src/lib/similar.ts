/**
 * Similarity ("more like this") client helpers.
 *
 * Mirrors services/core `api/schemas/similar.py`; all calls go through the
 * /api/core/similar BFF proxy.
 */

export type SimilarMethod = 'vector' | 'text';
export type AuthorMode = 'any' | 'same' | 'other';

/** A document type the index knows about. `conversation` is never embedded. */
export type SimilarDocType =
  | 'lead_post'
  | 'scout_post'
  | 'profile_item'
  | 'profile_snapshot'
  | 'account_comments'
  | 'message';

export interface SimilarRequest {
  doc_type?: SimilarDocType | string;
  entity_id?: number;
  text?: string;
  doc_types?: string[];
  author?: AuthorMode;
  location?: string;
  since?: string;
  until?: string;
  lead_status?: string[];
  include_deleted?: boolean;
  min_score?: number;
  limit?: number;
}

export interface SimilarHit {
  id: string;
  doc_type: string;
  entity_id: number | null;
  score: number;
  /** Cosine similarity (-1..1), or null when the match was text-only. */
  similarity: number | null;
  title: string | null;
  excerpt: string | null;
  author_username: string | null;
  account_id: number | null;
  location: string | null;
  created_at: string | null;
  post_url: string | null;
  lead_status: string | null;
  recommendation: string | null;
  priority: string | null;
  compatibility_score: number | null;
  human_verdict: string | null;
  author_banned: boolean;
}

export interface SimilarResponse {
  method: SimilarMethod;
  min_score: number;
  source: {
    doc_type: string | null;
    entity_id: number | null;
    author_username: string | null;
  };
  results: SimilarHit[];
}

export const DOC_TYPE_LABELS: Record<string, string> = {
  lead_post: 'Lead',
  scout_post: 'Scout post',
  profile_item: 'Profile item',
  profile_snapshot: 'Profile',
  account_comments: 'Comments',
  message: 'Message',
};

export const AUTHOR_MODE_LABELS: Record<AuthorMode, string> = {
  any: 'Anyone',
  same: 'Same author',
  other: 'Other authors',
};

/** Outcome badge styling, keyed by lead status. */
export const LEAD_STATUS_STYLE: Record<string, string> = {
  new: 'border-border text-muted-foreground',
  saved: 'border-border text-muted-foreground',
  contact_queued: 'border-sky-500/40 text-sky-700 dark:text-sky-300',
  contacted: 'border-sky-500/40 text-sky-700 dark:text-sky-300',
  engaged: 'border-emerald-500/40 text-emerald-700 dark:text-emerald-300',
  ignored: 'border-red-500/40 text-red-700 dark:text-red-300',
  expired: 'border-border text-muted-foreground',
};

export const RECOMMENDATION_STYLE: Record<string, string> = {
  suitable: 'text-emerald-700 dark:text-emerald-300',
  needs_review: 'text-amber-700 dark:text-amber-300',
  not_recommended: 'text-red-700 dark:text-red-300',
};

export function similarityPercent(hit: SimilarHit): string | null {
  if (hit.similarity === null) return null;
  return `${Math.round(hit.similarity * 100)}%`;
}

/** Where a neighbour lives in the app, or null when it has no page. */
export function hitHref(hit: SimilarHit): string | null {
  switch (hit.doc_type) {
    case 'lead_post':
      return hit.entity_id ? `/leads/${hit.entity_id}` : null;
    case 'profile_snapshot':
    case 'account_comments':
    case 'profile_item':
      return hit.account_id ? `/profile/${hit.account_id}` : null;
    default:
      return null;
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

/** Ask the core API what else reads like this. */
export async function fetchSimilar(request: SimilarRequest): Promise<SimilarResponse> {
  const response = await fetch('/api/core/similar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const message =
      typeof detail === 'string'
        ? detail
        : detail?.error || detail?.code || `Request failed (${response.status})`;
    throw new Error(message);
  }
  return data as SimilarResponse;
}
