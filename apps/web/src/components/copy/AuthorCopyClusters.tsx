'use client';

import { useEffect, useState } from 'react';
import { CopyBadge } from './CopyBadge';
import { fetchCopyClusters, type CopyClusterSummary } from '@/lib/copyClusters';

/**
 * Profile-page strip: the copy clusters this author has posted in. Renders
 * nothing when there are none (or the lookup fails — it is context only).
 */
export function AuthorCopyClusters({ username }: { username: string | null | undefined }) {
  const [clusters, setClusters] = useState<CopyClusterSummary[]>([]);

  useEffect(() => {
    if (!username) return;
    let cancelled = false;
    fetchCopyClusters({ author: username, limit: 20 })
      .then((page) => {
        if (!cancelled) setClusters(page.items);
      })
      .catch(() => {
        if (!cancelled) setClusters([]);
      });
    return () => {
      cancelled = true;
    };
  }, [username]);

  if (clusters.length === 0) return null;

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-sm" data-testid="author-copies">
      <span className="text-muted-foreground">Text also posted by other accounts:</span>
      {clusters.map((c) => (
        <CopyBadge
          key={c.id}
          copy={{
            cluster_id: c.id,
            kind: c.kind,
            computed_kind: c.computed_kind,
            decision: c.decision,
            author_count: c.author_count,
            earliest_other_posted_at: null,
          }}
        />
      ))}
    </div>
  );
}
