'use client';

import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, Loader2, RefreshCw } from 'lucide-react';
import { EmptyState } from '@/components/EmptyState';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { CopyClusterDrawer } from './CopyClusterDrawer';
import {
  fetchCopyClusters,
  formatDay,
  kindLabel,
  kindStyle,
  type CopyClusterSummary,
} from '@/lib/copyClusters';
import { cn } from '@/lib/utils';

const ALL = 'all';

const KIND_FILTERS = [
  { value: ALL, label: 'All kinds' },
  { value: 'ring_suspect', label: 'Ring suspects' },
  { value: 'confirmed_ring', label: 'Confirmed rings' },
  { value: 'returning_author', label: 'Returning authors' },
  { value: 'same_person', label: 'Same person' },
  { value: 'unclassified', label: 'Unclassified' },
];

const HANDLED_FILTERS = [
  { value: ALL, label: 'Handled or not' },
  { value: 'false', label: 'Needs a look' },
  { value: 'true', label: 'Handled automatically' },
];

const DECISION_FILTERS = [
  { value: ALL, label: 'Decided or not' },
  { value: 'none', label: 'Undecided' },
  { value: 'confirmed_ring', label: 'Confirmed ring' },
  { value: 'same_person', label: 'Same person' },
  { value: 'coincidence', label: 'Coincidence (dissolved)' },
];

/**
 * Copies tab on /leads: copy clusters newest first, filterable by kind and
 * decision. A row opens the cluster drawer, where decisions are made.
 */
export function CopyClustersTab() {
  const [kind, setKind] = useState(ALL);
  const [decision, setDecision] = useState('none');
  // Spam rings are skipped and hidden automatically; by default list the rest.
  const [handled, setHandled] = useState('false');
  const [items, setItems] = useState<CopyClusterSummary[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);

  const load = useCallback(
    async (cursor: string | null) => {
      if (cursor) setLoadingMore(true);
      else setLoading(true);
      setError(null);
      try {
        const page = await fetchCopyClusters({
          kind: kind === ALL ? undefined : kind,
          decision: decision === ALL ? undefined : decision,
          handled: handled === ALL ? undefined : handled === 'true',
          cursor,
        });
        setItems((prev) => (cursor ? [...prev, ...page.items] : page.items));
        setNextCursor(page.next_cursor);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load copy clusters');
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [kind, decision, handled],
  );

  useEffect(() => {
    load(null);
  }, [load]);

  const replace = (updated: CopyClusterSummary) =>
    setItems((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={kind} onValueChange={setKind}>
          <SelectTrigger className="w-44" aria-label="Filter by kind">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {KIND_FILTERS.map((f) => (
              <SelectItem key={f.value} value={f.value}>
                {f.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={decision} onValueChange={setDecision}>
          <SelectTrigger className="w-52" aria-label="Filter by decision">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DECISION_FILTERS.map((f) => (
              <SelectItem key={f.value} value={f.value}>
                {f.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={handled} onValueChange={setHandled}>
          <SelectTrigger className="w-48" aria-label="Filter by automatic handling">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {HANDLED_FILTERS.map((f) => (
              <SelectItem key={f.value} value={f.value}>
                {f.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button variant="ghost" size="sm" onClick={() => load(null)} aria-label="Refresh">
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      <p className="text-sm text-muted-foreground">
        The same text posted by different accounts, newest cluster first. Spam rings (3+
        accounts, posts of 400+ characters, or any cluster you confirmed as a ring) are handled
        automatically: the scout skips them and their leads are hidden. The rest are listed here
        for a look.
      </p>

      {loading ? (
        <div className="flex items-center justify-center h-48">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : error && items.length === 0 ? (
        <Card className="p-8">
          <div className="text-center">
            <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
            <p className="text-destructive font-medium">{error}</p>
            <Button variant="outline" onClick={() => load(null)} className="mt-4">
              Try Again
            </Button>
          </div>
        </Card>
      ) : items.length === 0 ? (
        <EmptyState
          icon="🧬"
          title="No copy clusters"
          description="No posts by different accounts share their text under these filters. Clusters appear as posts are fingerprinted."
        />
      ) : (
        <>
          <ul className="space-y-2">
            {items.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  data-testid="copy-cluster-row"
                  onClick={() => setOpenId(c.id)}
                  className="w-full text-left rounded-lg border border-border bg-card p-3 hover:bg-muted/40 transition-colors"
                >
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-medium">Cluster #{c.id}</span>
                    <span
                      className={cn(
                        'inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs font-medium',
                        kindStyle(c.kind),
                      )}
                    >
                      {kindLabel(c.kind)}
                    </span>
                    {c.handled && (
                      <span className="inline-flex items-center rounded-md border border-border px-1.5 py-0.5 text-xs text-muted-foreground">
                        handled
                      </span>
                    )}
                    {c.decision && (
                      <span className="text-xs text-muted-foreground">
                        computed {kindLabel(c.computed_kind).toLowerCase()}
                      </span>
                    )}
                    <span className="ml-auto text-xs text-muted-foreground">
                      {c.author_count} authors · {c.member_count} posts ·{' '}
                      {formatDay(c.first_posted_at)} – {formatDay(c.last_posted_at)}
                    </span>
                  </div>
                </button>
              </li>
            ))}
          </ul>
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

      <CopyClusterDrawer
        clusterId={openId}
        open={openId != null}
        onOpenChange={(open) => {
          if (!open) setOpenId(null);
        }}
        onChanged={replace}
      />
    </div>
  );
}
