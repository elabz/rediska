'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  AlertCircle,
  CalendarDays,
  ChevronDown,
  ExternalLink,
  Loader2,
  RefreshCw,
  UserPlus,
  X,
} from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components';
import { EvaluationControl } from '@/components/evaluations/EvaluationControl';
import { BanControl } from '@/components/ban/BanControl';
import { cn } from '@/lib/utils';
import type { EffectiveEvaluation, EvaluationMap } from '@/lib/evaluations';

// Mirrors api/schemas/scout_watch.py NeedsReviewPostResponse
interface GateResult {
  gate: string;
  status: string;
  reason: string;
}

export interface NeedsReviewItem {
  id: number;
  watch_id: number;
  external_post_id: string;
  post_title: string | null;
  post_body: string | null;
  post_author: string | null;
  first_seen_at: string;
  user_interests: string | null;
  user_character: string | null;
  analysis_confidence: number | null;
  analysis_reasoning: string | null;
  analysis_dimensions: Record<string, unknown> | null;
  evaluations: EvaluationMap;
  watch_source_location: string | null;
  watch_search_query: string | null;
}

interface NeedsReviewResponse {
  items: NeedsReviewItem[];
  total: number;
  next_cursor: string | null;
}

const PAGE_SIZE = 25;
const TIMEZONE = 'America/New_York';

const GATE_STYLE: Record<string, string> = {
  pass: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/30 dark:text-emerald-300',
  unclear: 'bg-amber-500/10 text-amber-700 border-amber-500/30 dark:text-amber-300',
  fail: 'bg-red-500/10 text-red-700 border-red-500/30 dark:text-red-300',
};

function gateResults(item: NeedsReviewItem): GateResult[] {
  const verdict = item.analysis_dimensions?.gate_verdict as
    | { gate_results?: GateResult[] }
    | undefined;
  return Array.isArray(verdict?.gate_results) ? verdict.gate_results : [];
}

function formatAge(dateString: string): string {
  const diffMs = Date.now() - new Date(dateString).getTime();
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 60) return `${Math.max(minutes, 0)}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function toUtc(dateString: string): string {
  // Core returns naive UTC timestamps for scout posts.
  return /[zZ]|[+-]\d\d:\d\d$/.test(dateString) ? dateString : `${dateString}Z`;
}

function QueueCard({
  item,
  busy,
  error,
  onPromote,
  onDismiss,
  onEvaluated,
  onBanned,
}: {
  item: NeedsReviewItem;
  busy: 'promote' | 'dismiss' | null;
  error: string | null;
  onPromote: () => void;
  onDismiss: () => void;
  onEvaluated: (saved: EffectiveEvaluation) => void;
  onBanned: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const gates = gateResults(item);
  const nonPassing = gates.filter((g) => g.status !== 'pass');
  const seen = toUtc(item.first_seen_at);
  const body = item.post_body || '';
  const longBody = body.length > 400;

  return (
    <Card className="p-4 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h3 className="font-medium text-sm leading-tight">{item.post_title || '(No title)'}</h3>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span
              className="inline-flex items-center gap-1 font-medium text-foreground"
              title={new Date(seen).toLocaleString('en-US', {
                timeZone: TIMEZONE,
                dateStyle: 'medium',
                timeStyle: 'short',
              })}
            >
              <CalendarDays className="h-3.5 w-3.5" />
              First seen {formatAge(seen)}
            </span>
            {item.watch_source_location && (
              <Link
                href={`/settings/scout-watches/${item.watch_id}/history`}
                className="text-blue-500 hover:underline"
              >
                r/{item.watch_source_location}
                {item.watch_search_query ? ` · "${item.watch_search_query}"` : ''}
              </Link>
            )}
            {item.post_author && (
              <a
                href={`https://www.reddit.com/user/${item.post_author}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary hover:underline"
              >
                u/{item.post_author}
              </a>
            )}
            <a
              href={`https://reddit.com/comments/${item.external_post_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-blue-500 hover:underline"
            >
              <ExternalLink className="h-3 w-3" /> Source
            </a>
          </div>
        </div>
        {item.analysis_confidence !== null && (
          <Badge variant="secondary" className="shrink-0">
            {Math.round(item.analysis_confidence * 100)}% score
          </Badge>
        )}
      </div>

      {/* Why it needs a human */}
      <div className="flex flex-wrap gap-1.5">
        {gates.length === 0 && (
          <span className="text-xs text-muted-foreground">No gate results stored.</span>
        )}
        {gates.map((g) => (
          <Badge
            key={g.gate}
            variant="outline"
            className={cn('text-xs font-normal', GATE_STYLE[g.status] ?? '')}
            title={g.reason}
          >
            {g.gate}: {g.status}
          </Badge>
        ))}
      </div>
      {nonPassing.length > 0 && (
        <ul className="text-xs text-muted-foreground list-disc pl-4 space-y-0.5">
          {nonPassing.map((g) => (
            <li key={g.gate}>
              <span className="font-medium">{g.gate}</span>: {g.reason}
            </li>
          ))}
        </ul>
      )}

      {body ? (
        <div>
          <p className="text-sm text-muted-foreground whitespace-pre-wrap break-words">
            {expanded || !longBody ? body : `${body.slice(0, 400)}...`}
          </p>
          {longBody && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setExpanded(!expanded)}
              className="mt-1 h-6 px-2 text-xs"
            >
              {expanded ? 'Show less' : 'Show more'}
              <ChevronDown className={cn('h-3 w-3 ml-1 transition-transform', expanded && 'rotate-180')} />
            </Button>
          )}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">No post body stored.</p>
      )}

      {error && (
        <p className="text-xs text-destructive flex items-center gap-1">
          <AlertCircle className="h-3.5 w-3.5" /> {error}
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-border">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-medium uppercase text-muted-foreground">Your verdict</span>
          <EvaluationControl
            subjectType="scout_post"
            subjectId={item.id}
            dimension={null}
            evaluation={item.evaluations?.final ?? null}
            agentRecommendation="needs_review"
            onSaved={onEvaluated}
            size="xs"
          />
        </div>
        <div className="flex items-center gap-2">
          {/* The queue already excludes banned authors, so no status lookup. */}
          <BanControl
            username={item.post_author}
            variant="compact"
            assumeNotBanned
            onChange={(ban) => ban && onBanned()}
          />
          <Button variant="ghost" size="sm" onClick={onDismiss} disabled={busy !== null}>
            {busy === 'dismiss' ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <>
                <X className="h-4 w-4 mr-1" />
                Dismiss
              </>
            )}
          </Button>
          <Button size="sm" onClick={onPromote} disabled={busy !== null}>
            {busy === 'promote' ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <>
                <UserPlus className="h-4 w-4 mr-1" />
                Promote to lead
              </>
            )}
          </Button>
        </div>
      </div>
    </Card>
  );
}

/**
 * Cross-watch needs-review triage queue: scout posts the gates could not
 * settle, newest first, with one-click promote and dismiss.
 */
export function NeedsReviewQueue({ onCountChange }: { onCountChange?: (count: number) => void }) {
  const [items, setItems] = useState<NeedsReviewItem[]>([]);
  const [total, setTotal] = useState(0);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<number, 'promote' | 'dismiss'>>({});
  const [itemErrors, setItemErrors] = useState<Record<number, string>>({});
  const [promoted, setPromoted] = useState<{ postId: number; leadId: number } | null>(null);

  const load = useCallback(
    async (cursor: string | null) => {
      if (cursor) setLoadingMore(true);
      else setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
        if (cursor) params.set('cursor', cursor);
        const response = await fetch(`/api/core/scout-watches/needs-review?${params}`, {
          credentials: 'include',
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(typeof data.detail === 'string' ? data.detail : 'Failed to load queue');
        }
        const page = data as NeedsReviewResponse;
        setItems((prev) => (cursor ? [...prev, ...page.items] : page.items));
        setTotal(page.total);
        setNextCursor(page.next_cursor);
        onCountChange?.(page.total);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load queue');
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [onCountChange]
  );

  useEffect(() => {
    load(null);
  }, [load]);

  const removeItem = (postId: number) => {
    setItems((prev) => prev.filter((i) => i.id !== postId));
    setTotal((prev) => {
      const next = Math.max(prev - 1, 0);
      onCountChange?.(next);
      return next;
    });
  };

  const act = async (item: NeedsReviewItem, action: 'promote' | 'dismiss') => {
    setBusy((prev) => ({ ...prev, [item.id]: action }));
    setItemErrors((prev) => {
      const next = { ...prev };
      delete next[item.id];
      return next;
    });
    try {
      const url =
        action === 'promote'
          ? `/api/core/scout-watches/${item.watch_id}/posts/${item.id}/add-to-leads`
          : `/api/core/scout-watches/posts/${item.id}/dismiss`;
      const response = await fetch(url, { method: 'POST', credentials: 'include' });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(typeof data.detail === 'string' ? data.detail : `Failed to ${action}`);
      }
      if (action === 'promote') setPromoted({ postId: item.id, leadId: data.lead_id });
      removeItem(item.id);
    } catch (err) {
      setItemErrors((prev) => ({
        ...prev,
        [item.id]: err instanceof Error ? err.message : `Failed to ${action}`,
      }));
    } finally {
      setBusy((prev) => {
        const next = { ...prev };
        delete next[item.id];
        return next;
      });
    }
  };

  const markEvaluated = (postId: number, saved: EffectiveEvaluation) => {
    setItems((prev) =>
      prev.map((i) =>
        i.id === postId ? { ...i, evaluations: { ...i.evaluations, final: saved } } : i
      )
    );
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error && items.length === 0) {
    return (
      <Card className="p-8">
        <div className="text-center">
          <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
          <p className="text-destructive font-medium">{error}</p>
          <Button variant="outline" onClick={() => load(null)} className="mt-4">
            Try Again
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {total} post{total !== 1 ? 's' : ''} the gates could not settle, newest first.
        </p>
        <Button variant="ghost" size="sm" onClick={() => load(null)}>
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      {promoted && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm flex items-center justify-between gap-2">
          <span>
            Promoted to{' '}
            <Link href={`/leads/${promoted.leadId}`} className="font-medium underline">
              Lead #{promoted.leadId}
            </Link>
          </span>
          <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => setPromoted(null)}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      )}

      {items.length === 0 ? (
        <EmptyState
          icon="✅"
          title="Nothing to review"
          description="No scout posts are waiting for a human decision. New needs-review posts appear here as watches run."
        />
      ) : (
        <>
          {items.map((item) => (
            <QueueCard
              key={item.id}
              item={item}
              busy={busy[item.id] ?? null}
              error={itemErrors[item.id] ?? null}
              onPromote={() => act(item, 'promote')}
              onDismiss={() => act(item, 'dismiss')}
              onEvaluated={(saved) => markEvaluated(item.id, saved)}
              onBanned={() => removeItem(item.id)}
            />
          ))}
          {error && <p className="text-sm text-destructive text-center">{error}</p>}
          {nextCursor && (
            <div className="flex justify-center">
              <Button variant="outline" onClick={() => load(nextCursor)} disabled={loadingMore}>
                {loadingMore && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                Load more
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
