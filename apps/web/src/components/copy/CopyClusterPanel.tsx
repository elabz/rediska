'use client';

import { useCallback, useEffect, useState } from 'react';
import { Copy, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CopyClusterDrawer, MemberRow, earliestAuthor } from './CopyClusterDrawer';
import {
  KIND_DESCRIPTIONS,
  fetchCopyCluster,
  kindLabel,
  kindStyle,
  type CopyClusterDetail,
  type CopyInfo,
} from '@/lib/copyClusters';
import { cn } from '@/lib/utils';

export interface CopyClusterPanelProps {
  copy: CopyInfo | null | undefined;
  /** This post; the panel lists the *other* posts of the same text. */
  externalPostId: string;
}

/**
 * Inline "same text, other accounts" section for lead detail: the other
 * authors with their account state, lead status, recommendation and verdict.
 * Context only — the lead's own analysis, priority and status are unchanged.
 */
export function CopyClusterPanel({ copy, externalPostId }: CopyClusterPanelProps) {
  const [detail, setDetail] = useState<CopyClusterDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const clusterId = copy?.cluster_id ?? null;

  const load = useCallback(async () => {
    if (clusterId == null) return;
    setError(null);
    try {
      setDetail(await fetchCopyCluster(clusterId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load copies');
    }
  }, [clusterId]);

  useEffect(() => {
    load();
  }, [load]);

  if (!copy) return null;

  const members = detail?.members ?? [];
  const earliest = earliestAuthor(members);
  const others = members.filter((m) => m.external_post_id !== externalPostId);
  const seen = new Set<string>();

  return (
    <div className="rounded-lg border border-border p-3 space-y-2" data-testid="copy-panel">
      <div className="flex flex-wrap items-center gap-2">
        <Copy className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm font-medium">Same text posted by other accounts</span>
        <span
          className={cn(
            'inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs font-medium',
            kindStyle(copy.kind),
          )}
        >
          {kindLabel(copy.kind)}
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto h-7 text-xs"
          onClick={() => setDrawerOpen(true)}
        >
          Open cluster #{copy.cluster_id}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        {KIND_DESCRIPTIONS[copy.kind] ?? ''}. Shown for context; this lead&apos;s own analysis is
        unchanged.
      </p>
      {error ? (
        <p className="text-xs text-destructive">
          {error}{' '}
          <button type="button" className="underline" onClick={load}>
            Retry
          </button>
        </p>
      ) : !detail ? (
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      ) : others.length === 0 ? (
        <p className="text-xs text-muted-foreground">No other posts are left in this cluster.</p>
      ) : (
        <ul className="space-y-2">
          {others.map((m) => {
            const key = (m.author_username ?? '').toLowerCase();
            const first = !seen.has(key);
            seen.add(key);
            return (
              <MemberRow
                key={m.member_id}
                member={m}
                showBan={first}
                current={false}
                earliest={first && key === earliest}
              />
            );
          })}
        </ul>
      )}
      <CopyClusterDrawer
        clusterId={copy.cluster_id}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        currentExternalPostId={externalPostId}
        onChanged={load}
      />
    </div>
  );
}
