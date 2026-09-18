'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertCircle, Ban, Loader2, X } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import {
  bulkBan,
  dismissBanSuggestion,
  fetchBanSuggestions,
  type BanSuggestion,
} from '@/lib/banList';
import { BanDialog } from './BanDialog';

function SuggestionCard({
  suggestion,
  onChanged,
}: {
  suggestion: BanSuggestion;
  onChanged: () => void;
}) {
  // Bulk ban excludes the earliest poster by default: they may be the victim
  // whose ad was copied, not a member of the ring.
  const [excluded, setExcluded] = useState<Set<string>>(
    () => new Set(suggestion.authors.filter((a) => a.earliest).map((a) => a.username)),
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [banOne, setBanOne] = useState<string | null>(null);

  const open = suggestion.authors.filter((a) => !a.banned && !a.dismissed);
  const toBan = open.filter((a) => !excluded.has(a.username));

  const toggle = (username: string) =>
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(username)) next.delete(username);
      else next.add(username);
      return next;
    });

  const run = async (key: string, action: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed');
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card className="p-4" data-testid="ban-suggestion">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-medium">Copy cluster #{suggestion.cluster_id}</span>
          <Badge variant="destructive" className="h-5 px-1.5 text-xs">
            {suggestion.kind.replace('_', ' ')}
          </Badge>
          <span className="text-xs text-muted-foreground">
            {suggestion.authors.length} authors
          </span>
        </div>
        <Button
          variant="destructive"
          size="sm"
          disabled={toBan.length === 0 || busy !== null}
          onClick={() =>
            run('bulk', () =>
              bulkBan({
                cluster_id: suggestion.cluster_id,
                reason: 'copy_ring',
                exclude_usernames: suggestion.authors
                  .filter((a) => excluded.has(a.username) || a.banned || a.dismissed)
                  .map((a) => a.username),
              }),
            )
          }
        >
          {busy === 'bulk' ? <Loader2 className="h-3 w-3 animate-spin" /> : <Ban className="h-3 w-3" />}
          Ban {toBan.length} selected
        </Button>
      </div>

      <ul className="space-y-2">
        {suggestion.authors.map((a) => {
          const actionable = !a.banned && !a.dismissed;
          return (
            <li
              key={a.username}
              className={cn(
                'flex flex-wrap items-center gap-3 rounded-md border border-border px-3 py-2 text-sm',
                !actionable && 'opacity-60',
              )}
            >
              <input
                type="checkbox"
                aria-label={`Include u/${a.username} in bulk ban`}
                checked={actionable && !excluded.has(a.username)}
                disabled={!actionable}
                onChange={() => toggle(a.username)}
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  {a.account_id ? (
                    <Link href={`/profile/${a.account_id}`} className="font-medium hover:underline">
                      u/{a.username}
                    </Link>
                  ) : (
                    <span className="font-medium">u/{a.username}</span>
                  )}
                  {a.earliest && (
                    <Badge variant="outline" className="h-5 px-1.5 text-xs">
                      earliest poster
                    </Badge>
                  )}
                  {a.banned && (
                    <Badge variant="destructive" className="h-5 px-1.5 text-xs">
                      banned
                    </Badge>
                  )}
                  {a.dismissed && (
                    <Badge variant="secondary" className="h-5 px-1.5 text-xs">
                      dismissed
                    </Badge>
                  )}
                  {a.remote_status && a.remote_status !== 'active' && (
                    <Badge variant="outline" className="h-5 px-1.5 text-xs">
                      {a.remote_status}
                    </Badge>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">
                  {a.first_posted_at
                    ? `First posted ${new Date(a.first_posted_at).toLocaleString()}`
                    : 'Post time unknown'}
                  {` · ${a.post_count} post${a.post_count === 1 ? '' : 's'}`}
                </p>
              </div>
              {actionable && (
                <div className="flex gap-1">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy !== null}
                    onClick={() => setBanOne(a.username)}
                  >
                    <Ban className="h-3 w-3" />
                    Ban
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy !== null}
                    onClick={() =>
                      run(`dismiss:${a.username}`, () =>
                        dismissBanSuggestion(suggestion.cluster_id, a.username),
                      )
                    }
                    title="Dismiss this suggestion"
                  >
                    {busy === `dismiss:${a.username}` ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <X className="h-3 w-3" />
                    )}
                    Dismiss
                  </Button>
                </div>
              )}
            </li>
          );
        })}
      </ul>

      {error && (
        <p className="mt-2 flex items-center gap-2 text-sm text-destructive" role="alert">
          <AlertCircle className="h-4 w-4" />
          {error}
        </p>
      )}

      <BanDialog
        open={banOne !== null}
        onOpenChange={(o) => !o && setBanOne(null)}
        username={banOne ?? ''}
        initialReason="copy_ring"
        onBanned={onChanged}
      />
    </Card>
  );
}

/**
 * Ban suggestions from copy-ring clusters. Nothing is banned without a click;
 * the queue is empty (with a note) until copy detection is installed.
 */
export function BanSuggestions() {
  const [items, setItems] = useState<BanSuggestion[]>([]);
  const [available, setAvailable] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchBanSuggestions();
      setAvailable(data.available);
      setItems(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load suggestions');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <div className="flex h-16 items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <Card className="p-4">
        <div className="flex items-center gap-3 text-sm text-destructive" role="alert">
          <AlertCircle className="h-4 w-4" />
          <span className="flex-1">{error}</span>
          <Button variant="outline" size="sm" onClick={load}>
            Try again
          </Button>
        </div>
      </Card>
    );
  }

  if (!available || items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="ban-suggestions-empty">
        {available
          ? 'No ban suggestions. Authors of suspected copy rings appear here for review.'
          : 'Ban suggestions appear here once copy detection is installed.'}
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {items.map((s) => (
        <SuggestionCard key={s.cluster_id} suggestion={s} onChanged={load} />
      ))}
    </div>
  );
}
