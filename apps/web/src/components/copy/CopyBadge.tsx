'use client';

import { useState } from 'react';
import { Copy } from 'lucide-react';
import { CopyClusterDrawer } from './CopyClusterDrawer';
import { formatDay, kindLabel, kindStyle, type CopyInfo } from '@/lib/copyClusters';
import { cn } from '@/lib/utils';

export interface CopyBadgeProps {
  /** The read model's `copy` field; nothing renders when it is null. */
  copy: CopyInfo | null | undefined;
  /** The post this badge sits on, highlighted in the drawer. */
  externalPostId?: string | null;
  className?: string;
}

/**
 * "Same text as N other accounts" marker. Click opens the cluster drawer with
 * what we already hold about the other authors. Safe inside links and cards.
 */
export function CopyBadge({ copy, externalPostId, className }: CopyBadgeProps) {
  const [open, setOpen] = useState(false);
  if (!copy) return null;

  const others = Math.max(copy.author_count - 1, 1);
  const earliest = copy.earliest_other_posted_at
    ? `; earliest other post ${formatDay(copy.earliest_other_posted_at)}`
    : '';

  return (
    <>
      <button
        type="button"
        data-testid="copy-badge"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen(true);
        }}
        title={`Same text as ${others} other account${others === 1 ? '' : 's'}${earliest}. Click for details.`}
        className={cn(
          'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs font-medium',
          'hover:opacity-80 focus:outline-none focus:ring-2 focus:ring-ring',
          kindStyle(copy.kind),
          className,
        )}
      >
        <Copy className="h-3 w-3" />
        {kindLabel(copy.kind)} · {copy.author_count} authors
        {copy.handled && ' · hidden'}
      </button>
      {open && (
        <span onClick={(e) => e.stopPropagation()}>
          <CopyClusterDrawer
            clusterId={copy.cluster_id}
            open={open}
            onOpenChange={setOpen}
            currentExternalPostId={externalPostId}
          />
        </span>
      )}
    </>
  );
}
