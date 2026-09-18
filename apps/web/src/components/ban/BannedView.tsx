'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertCircle, Ban, Loader2, Search, ShieldCheck } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { EmptyState } from '@/components/EmptyState';
import { cn } from '@/lib/utils';
import {
  SOURCE_LABELS,
  fetchBanList,
  liftBan,
  reasonLabel,
  type BanEntry,
  type BanSource,
  type BanStatus,
} from '@/lib/banList';
import { BanDialog } from './BanDialog';

const STATUS_FILTERS: { value: BanStatus | ''; label: string }[] = [
  { value: 'active', label: 'Active' },
  { value: 'lifted', label: 'Lifted' },
  { value: '', label: 'All' },
];

const SOURCE_FILTERS: { value: BanSource | ''; label: string }[] = [
  { value: '', label: 'Any source' },
  { value: 'manual', label: SOURCE_LABELS.manual },
  { value: 'copy_ring', label: SOURCE_LABELS.copy_ring },
  { value: 'import', label: SOURCE_LABELS.import },
];

function BanRow({
  entry,
  onLift,
  lifting,
}: {
  entry: BanEntry;
  onLift: (entry: BanEntry) => void;
  lifting: boolean;
}) {
  const active = entry.status === 'active';
  return (
    <Card className={cn('p-4', !active && 'opacity-70')} data-testid="ban-row">
      <div className="flex items-start gap-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-destructive/10">
          <Ban className="h-5 w-5 text-destructive" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {entry.account_id ? (
              <Link href={`/profile/${entry.account_id}`} className="font-medium hover:underline">
                u/{entry.username}
              </Link>
            ) : (
              <span className="font-medium">u/{entry.username}</span>
            )}
            <Badge variant={active ? 'destructive' : 'outline'} className="h-5 px-1.5 text-xs">
              {active ? 'banned' : 'lifted'}
            </Badge>
            <Badge variant="secondary" className="h-5 px-1.5 text-xs">
              {SOURCE_LABELS[entry.source] ?? entry.source}
            </Badge>
          </div>
          <p className="mt-1 text-sm">{reasonLabel(entry.reason)}</p>
          {entry.notes && (
            <p className="mt-1 whitespace-pre-line text-sm text-muted-foreground">{entry.notes}</p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span>Banned {new Date(entry.created_at).toLocaleDateString()}</span>
            {entry.lifted_at && (
              <span>Lifted {new Date(entry.lifted_at).toLocaleDateString()}</span>
            )}
            {entry.cluster_id != null && <span>Copy cluster #{entry.cluster_id}</span>}
            {entry.lead_ids.length > 0 && (
              <span className="flex flex-wrap items-center gap-1">
                Leads:
                {entry.lead_ids.slice(0, 5).map((id) => (
                  <Link key={id} href={`/leads/${id}`} className="underline hover:text-foreground">
                    #{id}
                  </Link>
                ))}
                {entry.lead_ids.length > 5 && <span>+{entry.lead_ids.length - 5}</span>}
              </span>
            )}
          </div>
        </div>
        {active && (
          <Button variant="outline" size="sm" onClick={() => onLift(entry)} disabled={lifting}>
            {lifting ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <ShieldCheck className="h-3 w-3" />
            )}
            Lift
          </Button>
        )}
      </div>
    </Card>
  );
}

/** The Banned directory: every ban entry, searchable, with lift. */
export function BannedView() {
  const [items, setItems] = useState<BanEntry[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [appliedQuery, setAppliedQuery] = useState('');
  const [status, setStatus] = useState<BanStatus | ''>('active');
  const [source, setSource] = useState<BanSource | ''>('');
  const [liftingId, setLiftingId] = useState<number | null>(null);
  const [banName, setBanName] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);

  const load = useCallback(
    async (cursor: string | null = null) => {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchBanList({ status, source, q: appliedQuery, cursor });
        setItems((prev) => (cursor ? [...prev, ...data.items] : data.items));
        setNextCursor(data.next_cursor);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load the ban list');
      } finally {
        setLoading(false);
      }
    },
    [status, source, appliedQuery],
  );

  useEffect(() => {
    load();
  }, [load]);

  const handleLift = async (entry: BanEntry) => {
    setLiftingId(entry.id);
    try {
      const result = await liftBan(entry.id);
      setItems((prev) =>
        status === 'active'
          ? prev.filter((e) => e.id !== entry.id)
          : prev.map((e) => (e.id === entry.id ? result.entry : e)),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to lift ban');
    } finally {
      setLiftingId(null);
    }
  };

  const cleanBanName = banName.trim().replace(/^\/?u\//i, '');

  return (
    <div className="space-y-4">
      {/* Ban by username */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
            u/
          </span>
          <Input
            placeholder="Ban a username..."
            value={banName}
            onChange={(e) => setBanName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && cleanBanName) {
                e.preventDefault();
                setDialogOpen(true);
              }
            }}
            className="h-9 pl-8"
            aria-label="Username to ban"
          />
        </div>
        <Button
          variant="destructive"
          size="sm"
          className="h-9"
          disabled={!cleanBanName}
          onClick={() => setDialogOpen(true)}
        >
          <Ban className="h-4 w-4" />
          Ban
        </Button>
      </div>
      <BanDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        username={cleanBanName}
        onBanned={() => {
          setBanName('');
          load();
        }}
      />

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search name, reason or notes..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                setAppliedQuery(query);
              }
            }}
            className="h-9 pl-9"
            aria-label="Search bans"
          />
        </div>
        <div className="flex gap-1 rounded-lg bg-muted p-1">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.label}
              type="button"
              onClick={() => setStatus(f.value)}
              className={cn(
                'rounded-md px-3 py-1 text-xs font-medium',
                status === f.value
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
        <select
          value={source}
          onChange={(e) => setSource(e.target.value as BanSource | '')}
          className="h-9 rounded-md border border-border bg-background px-2 text-sm"
          aria-label="Source"
        >
          {SOURCE_FILTERS.map((f) => (
            <option key={f.label} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <Card className="p-4">
          <div className="flex items-center gap-3 text-sm text-destructive" role="alert">
            <AlertCircle className="h-4 w-4" />
            <span className="flex-1">{error}</span>
            <Button variant="outline" size="sm" onClick={() => load()}>
              Try again
            </Button>
          </div>
        </Card>
      )}

      {loading && items.length === 0 ? (
        <div className="flex h-32 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : items.length === 0 && !error ? (
        <EmptyState
          icon="🚫"
          title={appliedQuery || source || status !== 'active' ? 'No matching bans' : 'Nobody is banned'}
          description="Ban an account from its conversation, profile, lead or scout post, or enter a username above. A banned account can never be messaged and its open leads move to Ignored."
        />
      ) : (
        <div className="space-y-3">
          {items.map((entry) => (
            <BanRow
              key={entry.id}
              entry={entry}
              onLift={handleLift}
              lifting={liftingId === entry.id}
            />
          ))}
          {nextCursor && (
            <div className="flex justify-center">
              <Button variant="outline" onClick={() => load(nextCursor)} disabled={loading}>
                {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                Load more
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
