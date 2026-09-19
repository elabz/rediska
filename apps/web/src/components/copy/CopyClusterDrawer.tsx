'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertCircle, Ban, Loader2 } from 'lucide-react';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { BanControl } from '@/components/ban/BanControl';
import { bulkBan } from '@/lib/banList';
import {
  DECISION_OPTIONS,
  KIND_DESCRIPTIONS,
  decideCopyCluster,
  fetchCopyCluster,
  formatDay,
  kindLabel,
  kindStyle,
  type CopyClusterDetail,
  type CopyClusterMember,
  type CopyClusterSummary,
  type CopyDecision,
} from '@/lib/copyClusters';
import { cn } from '@/lib/utils';

export interface CopyClusterDrawerProps {
  clusterId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The post the drawer was opened from, highlighted in the member list. */
  currentExternalPostId?: string | null;
  /** Called after a decision or a cluster ban, with the updated cluster. */
  onChanged?: (cluster: CopyClusterSummary) => void;
}

const REC_STYLE: Record<string, string> = {
  suitable: 'text-emerald-700 dark:text-emerald-300',
  needs_review: 'text-amber-700 dark:text-amber-300',
  not_recommended: 'text-red-700 dark:text-red-300',
};

/** Earliest poster first; their ad may be the one that was copied. */
export function earliestAuthor(members: CopyClusterMember[]): string | null {
  const first = members.find((m) => m.author_username);
  return first?.author_username?.toLowerCase() ?? null;
}

export function MemberRow({
  member,
  showBan,
  current,
  earliest,
}: {
  member: CopyClusterMember;
  showBan: boolean;
  current: boolean;
  earliest: boolean;
}) {
  const name = member.author_username;
  return (
    <li
      data-testid="copy-member"
      className={cn(
        'rounded-md border border-border px-3 py-2 text-sm space-y-1',
        current && 'border-primary/60 bg-primary/5',
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        {name ? (
          member.account_id ? (
            <Link href={`/profile/${member.account_id}`} className="font-medium hover:underline">
              u/{name}
            </Link>
          ) : (
            <span className="font-medium">u/{name}</span>
          )
        ) : (
          <span className="text-muted-foreground">unknown author</span>
        )}
        {earliest && (
          <Badge variant="outline" className="h-5 px-1.5 text-xs">
            earliest poster
          </Badge>
        )}
        {current && (
          <Badge variant="secondary" className="h-5 px-1.5 text-xs">
            this post
          </Badge>
        )}
        {member.remote_status && member.remote_status !== 'active' && (
          <Badge variant="outline" className="h-5 px-1.5 text-xs">
            account {member.remote_status}
          </Badge>
        )}
        {member.ban_status === 'active' && (
          <Badge variant="destructive" className="h-5 px-1.5 text-xs">
            banned
          </Badge>
        )}
        {member.repost_of_id && (
          <Badge variant="outline" className="h-5 px-1.5 text-xs">
            repost
          </Badge>
        )}
        <span className="ml-auto" />
        {showBan && name && <BanControl username={name} variant="compact" />}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span title={member.posted_at ? 'Posted' : 'First seen'}>
          {formatDay(member.posted_at ?? member.first_seen_at)}
        </span>
        {member.location && <span>{member.location}</span>}
        <span>via {member.source.replace('_', ' ')}</span>
        {member.similarity != null && <span>{Math.round(member.similarity * 100)}% similar</span>}
        {member.lead_id && (
          <Link href={`/leads/${member.lead_id}`} className="text-blue-500 hover:underline">
            Lead #{member.lead_id}
            {member.lead_status ? ` · ${member.lead_status.replace('_', ' ')}` : ''}
          </Link>
        )}
        {member.scout_watch_id && (
          <Link
            href={`/settings/scout-watches/${member.scout_watch_id}/history`}
            className="text-blue-500 hover:underline"
          >
            Scout history
          </Link>
        )}
        {member.recommendation && (
          <span className={REC_STYLE[member.recommendation] ?? ''}>
            {member.recommendation.replace('_', ' ')}
          </span>
        )}
        {member.human_verdict && <span>you: {member.human_verdict}</span>}
      </div>
    </li>
  );
}

/**
 * Everything already held about a copy cluster: who posted the text, when,
 * their account state, leads, analyses and verdicts. Decisions and bans are
 * explicit user actions; nothing here changes a lead or an analysis.
 */
export function CopyClusterDrawer({
  clusterId,
  open,
  onOpenChange,
  currentExternalPostId,
  onChanged,
}: CopyClusterDrawerProps) {
  const [detail, setDetail] = useState<CopyClusterDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notes, setNotes] = useState('');
  const [confirm, setConfirm] = useState<'coincidence' | 'ban' | null>(null);
  const [banned, setBanned] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (clusterId == null) return;
    setLoading(true);
    setError(null);
    try {
      setDetail(await fetchCopyCluster(clusterId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load copy cluster');
    } finally {
      setLoading(false);
    }
  }, [clusterId]);

  useEffect(() => {
    if (open) {
      setConfirm(null);
      setActionError(null);
      setBanned(null);
      load();
    }
  }, [open, load]);

  const members = detail?.members ?? [];
  const cluster = detail?.cluster;
  const earliest = earliestAuthor(members);
  const seenAuthors = new Set<string>();
  const banTargets = Array.from(
    new Set(
      members
        .filter((m) => m.author_username && m.ban_status !== 'active')
        .map((m) => m.author_username!.toLowerCase()),
    ),
  ).filter((name) => name !== earliest);

  const decide = async (decision: CopyDecision | null) => {
    if (!cluster) return;
    if (decision === 'coincidence' && confirm !== 'coincidence') {
      setConfirm('coincidence');
      return;
    }
    setBusy(decision ?? 'clear');
    setActionError(null);
    try {
      const updated = await decideCopyCluster(cluster.id, decision, notes);
      onChanged?.(updated);
      setConfirm(null);
      setNotes('');
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Decision failed');
    } finally {
      setBusy(null);
    }
  };

  const banCluster = async () => {
    if (!cluster) return;
    if (confirm !== 'ban') {
      setConfirm('ban');
      return;
    }
    setBusy('ban');
    setActionError(null);
    try {
      const result = await bulkBan({
        cluster_id: cluster.id,
        reason: 'copy_ring',
        exclude_usernames: earliest ? [earliest] : [],
      });
      setBanned(result.banned.length);
      setConfirm(null);
      onChanged?.(cluster);
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Ban failed');
    } finally {
      setBusy(null);
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-2xl overflow-y-auto" data-testid="copy-drawer">
        <SheetHeader>
          <SheetTitle>Copy cluster {clusterId != null ? `#${clusterId}` : ''}</SheetTitle>
          <SheetDescription>
            The same text posted by different accounts. Shown for context: nothing here
            changes a lead or an analysis.
          </SheetDescription>
        </SheetHeader>

        {loading && !detail && (
          <div className="flex items-center justify-center h-40">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        )}

        {error && (
          <div className="mt-6 text-center space-y-3">
            <AlertCircle className="h-8 w-8 text-destructive mx-auto" />
            <p className="text-sm text-destructive">{error}</p>
            <Button variant="outline" size="sm" onClick={load}>
              Try again
            </Button>
          </div>
        )}

        {cluster && (
          <div className="mt-4 space-y-4">
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={cn(
                    'inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold',
                    kindStyle(cluster.kind),
                  )}
                >
                  {kindLabel(cluster.kind)}
                </span>
                {cluster.decision && (
                  <span className="text-xs text-muted-foreground">
                    computed: {kindLabel(cluster.computed_kind)}
                  </span>
                )}
                <span className="text-xs text-muted-foreground">
                  {cluster.author_count} authors · {cluster.member_count} posts ·{' '}
                  {formatDay(cluster.first_posted_at)} – {formatDay(cluster.last_posted_at)}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">
                {KIND_DESCRIPTIONS[cluster.kind] ?? ''}
              </p>
              {cluster.handled && (
                <p className="text-xs text-muted-foreground">
                  Handled automatically as a spam ring: the scout skips this text and its leads
                  are hidden from the lead list. Mark it Same person or Coincidence to undo.
                </p>
              )}
              {cluster.decision_notes && (
                <p className="text-xs">Notes: {cluster.decision_notes}</p>
              )}
            </div>

            {cluster.decision !== 'coincidence' && (
              <div className="space-y-2 rounded-md border border-border p-3">
                <p className="text-xs font-medium">Your reading of this cluster</p>
                <div className="flex flex-wrap gap-2">
                  {DECISION_OPTIONS.map((opt) => (
                    <Button
                      key={opt.value}
                      size="sm"
                      variant={cluster.decision === opt.value ? 'default' : 'outline'}
                      disabled={busy !== null}
                      onClick={() => decide(opt.value)}
                    >
                      {busy === opt.value && <Loader2 className="h-3 w-3 animate-spin" />}
                      {confirm === 'coincidence' && opt.value === 'coincidence'
                        ? 'Confirm: dissolve cluster'
                        : opt.label}
                    </Button>
                  ))}
                  {cluster.decision && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy !== null}
                      onClick={() => decide(null)}
                    >
                      Clear decision
                    </Button>
                  )}
                </div>
                {confirm === 'coincidence' && (
                  <p className="text-xs text-muted-foreground">
                    Coincidence dissolves the cluster and stops these texts from clustering again.
                  </p>
                )}
                <Input
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Notes (optional)"
                  className="h-8 text-xs"
                />
              </div>
            )}

            {members.length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={banTargets.length === 0 || busy !== null}
                  onClick={banCluster}
                >
                  {busy === 'ban' ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Ban className="h-3 w-3" />
                  )}
                  {confirm === 'ban'
                    ? `Confirm: ban ${banTargets.length}`
                    : `Ban cluster (${banTargets.length})`}
                </Button>
                <span className="text-xs text-muted-foreground">
                  Excludes the earliest poster and accounts already banned.
                </span>
                {banned != null && (
                  <span className="text-xs text-emerald-700 dark:text-emerald-300">
                    Banned {banned}.
                  </span>
                )}
              </div>
            )}

            {actionError && <p className="text-sm text-destructive">{actionError}</p>}

            {members.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                This cluster has no members (it was dissolved as a coincidence).
              </p>
            ) : (
              <ul className="space-y-2">
                {members.map((m) => {
                  const key = (m.author_username ?? '').toLowerCase();
                  const firstOfAuthor = !seenAuthors.has(key);
                  seenAuthors.add(key);
                  return (
                    <MemberRow
                      key={m.member_id}
                      member={m}
                      showBan={firstOfAuthor}
                      current={m.external_post_id === currentExternalPostId}
                      earliest={firstOfAuthor && key === earliest}
                    />
                  );
                })}
              </ul>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
