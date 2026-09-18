'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  AlertCircle,
  BellOff,
  Compass,
  ExternalLink,
  FlaskConical,
  Loader2,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Square,
  X,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';

// =============================================================================
// TYPES
// =============================================================================

export interface LocationInfo {
  name: string;
  title?: string | null;
  description?: string | null;
  member_count?: number | null;
  active_count?: number | null;
  is_nsfw: boolean;
}

export interface TrialYield {
  posts_fetched: number;
  skipped_empty: number;
  link_only_resolved: number;
  suitable: number;
  needs_review: number;
  not_recommended: number;
  skipped_prior_verdict: number;
  failed: number;
  top_failing_gate: string | null;
  top_failing_gate_count: number;
  median_post_age_hours: number | null;
}

export interface SourceTrial {
  id: number;
  candidate_id: number;
  watch_id: number | null;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  sample_size: number;
  posts_total: number;
  progress: number;
  yield_report: TrialYield | null;
  error: string | null;
}

export interface SourceCandidate {
  id: number;
  kind: 'location' | 'external_host';
  name: string;
  origin: 'mined' | 'manual';
  status: 'new' | 'trialled' | 'accepted' | 'dismissed' | 'snoozed';
  lift: number | null;
  evidence_count: number;
  evidence: Record<string, unknown>;
  snoozed_until: string | null;
  location_info: LocationInfo | null;
  location_unavailable: boolean;
  watch_id: number | null;
  latest_trial: SourceTrial | null;
}

interface CandidateListResponse {
  items: SourceCandidate[];
  total: number;
  next_cursor: string | null;
  running_trial: SourceTrial | null;
}

interface SearchResult extends LocationInfo {
  watched: boolean;
  candidate_id: number | null;
  candidate_status: string | null;
}

type View = 'open' | 'dismissed' | 'accepted';

const POLL_INTERVAL_MS = 10_000;
const SNOOZE_DAYS = 30;

// =============================================================================
// HELPERS
// =============================================================================

async function postJson(url: string, body: unknown = {}): Promise<unknown> {
  const response = await fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error((data as { detail?: string }).detail || 'Request failed');
  }
  return data;
}

function num(value: unknown): number {
  return typeof value === 'number' ? value : 0;
}

function formatCount(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n);
}

function isActiveTrial(trial: SourceTrial | null): boolean {
  return !!trial && (trial.status === 'queued' || trial.status === 'running');
}

// =============================================================================
// SUB-COMPONENTS
// =============================================================================

function Evidence({ candidate }: { candidate: SourceCandidate }) {
  const ev = candidate.evidence;
  if (candidate.kind === 'external_host') {
    const examples = Array.isArray(ev.example_urls) ? (ev.example_urls as string[]) : [];
    return (
      <div className="space-y-1 text-xs text-muted-foreground">
        <p>
          {num(ev.occurrences)} distinct links seen · needs a parser before it can be used
          (never fetched)
        </p>
        {examples.length > 0 && (
          <ul className="space-y-0.5">
            {examples.map((url) => (
              <li key={url} className="truncate">
                <a
                  href={url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex items-center gap-1 hover:underline"
                >
                  <ExternalLink className="h-3 w-3 shrink-0" />
                  {url}
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }
  if (candidate.origin === 'manual' && !ev.qualified_authors) {
    return <p className="text-xs text-muted-foreground">Added from search</p>;
  }
  return (
    <p className="text-xs text-muted-foreground">
      {num(ev.qualified_authors)} of {num(ev.qualified_total)} qualified authors ·{' '}
      {num(ev.analysed_authors)} of {num(ev.analysed_total)} analysed authors post here
    </p>
  );
}

function LocationDetails({ candidate }: { candidate: SourceCandidate }) {
  if (candidate.kind !== 'location') return null;
  if (candidate.location_unavailable) {
    return <p className="text-xs text-destructive">Private, banned, or no longer exists</p>;
  }
  const info = candidate.location_info;
  if (!info) return null;
  return (
    <div className="text-xs text-muted-foreground space-y-0.5">
      <p>
        {formatCount(info.member_count)} members
        {info.active_count ? ` · ${formatCount(info.active_count)} online` : ''}
      </p>
      {info.description && <p className="line-clamp-2">{info.description}</p>}
    </div>
  );
}

function TrialSummary({
  trial,
  onCancel,
  busy,
}: {
  trial: SourceTrial;
  onCancel: () => void;
  busy: boolean;
}) {
  if (isActiveTrial(trial)) {
    const total = trial.posts_total || trial.sample_size;
    return (
      <div className="flex items-center gap-3 rounded-md bg-blue-500/10 px-3 py-2 text-xs">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />
        <span data-testid="trial-progress">
          {trial.status === 'queued'
            ? 'Trial queued'
            : `Trial: ${trial.progress} of ${total} posts analysed`}
        </span>
        <Button variant="ghost" size="sm" className="ml-auto h-6" onClick={onCancel} disabled={busy}>
          <Square className="h-3 w-3 mr-1" />
          Cancel
        </Button>
      </div>
    );
  }
  if (trial.status === 'failed') {
    return <p className="text-xs text-destructive">Trial failed: {trial.error}</p>;
  }
  const y = trial.yield_report;
  if (!y) return null;
  return (
    <div className="rounded-md bg-muted/50 px-3 py-2 text-xs space-y-0.5" data-testid="trial-yield">
      <p className="font-medium">
        {trial.status === 'cancelled' ? 'Partial trial' : 'Trial'} yield:{' '}
        <span className="text-emerald-600 dark:text-emerald-400">{y.suitable} suitable</span> ·{' '}
        <span className="text-amber-600 dark:text-amber-400">{y.needs_review} needs review</span> ·{' '}
        {y.not_recommended} not recommended
      </p>
      <p className="text-muted-foreground">
        {y.posts_fetched} fetched · {y.skipped_empty} empty · {y.link_only_resolved} link-only
        resolved
        {y.top_failing_gate
          ? ` · top failing gate: ${y.top_failing_gate} (${y.top_failing_gate_count})`
          : ''}
        {y.median_post_age_hours !== null ? ` · median age ${y.median_post_age_hours}h` : ''}
      </p>
    </div>
  );
}

// =============================================================================
// MAIN
// =============================================================================

interface DiscoverTabProps {
  onCreateWatch: (candidate: SourceCandidate) => void;
}

export function DiscoverTab({ onCreateWatch }: DiscoverTabProps) {
  const [view, setView] = useState<View>('open');
  const [items, setItems] = useState<SourceCandidate[]>([]);
  const [total, setTotal] = useState(0);
  const [runningTrial, setRunningTrial] = useState<SourceTrial | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [results, setResults] = useState<SearchResult[] | null>(null);

  const fetchCandidates = useCallback(
    async (quiet = false) => {
      if (!quiet) {
        setLoading(true);
        setError(null);
      }
      try {
        const params = new URLSearchParams({ limit: '100' });
        if (view !== 'open') params.set('status', view);
        const response = await fetch(`/api/core/source-candidates?${params}`, {
          credentials: 'include',
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.detail || 'Failed to load candidates');
        }
        const list = data as CandidateListResponse;
        setItems(list.items);
        setTotal(list.total);
        setRunningTrial(list.running_trial);
      } catch (err) {
        if (!quiet) setError(err instanceof Error ? err.message : 'An error occurred');
      } finally {
        if (!quiet) setLoading(false);
      }
    },
    [view],
  );

  useEffect(() => {
    fetchCandidates();
  }, [fetchCandidates]);

  // Poll while a trial is queued or running so progress updates on its own.
  useEffect(() => {
    if (!isActiveTrial(runningTrial)) return;
    const timer = setInterval(() => fetchCandidates(true), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [runningTrial, fetchCandidates]);

  const act = async (candidateId: number, run: () => Promise<unknown>) => {
    setBusyId(candidateId);
    setActionError(null);
    try {
      await run();
      await fetchCandidates(true);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Action failed');
    } finally {
      setBusyId(null);
    }
  };

  const base = '/api/core/source-candidates';
  const dismiss = (c: SourceCandidate) => act(c.id, () => postJson(`${base}/${c.id}/dismiss`));
  const restore = (c: SourceCandidate) => act(c.id, () => postJson(`${base}/${c.id}/restore`));
  const trial = (c: SourceCandidate) => act(c.id, () => postJson(`${base}/${c.id}/trial`));
  const snooze = (c: SourceCandidate) =>
    act(c.id, () =>
      postJson(`${base}/${c.id}/snooze`, {
        until: new Date(Date.now() + SNOOZE_DAYS * 86_400_000).toISOString(),
      }),
    );
  const cancelTrial = (c: SourceCandidate, t: SourceTrial) =>
    act(c.id, () => postJson(`${base}/trials/${t.id}/cancel`));

  const search = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setSearchError(null);
    try {
      const response = await fetch(
        `${base}/search?${new URLSearchParams({ q: query.trim() })}`,
        { credentials: 'include' },
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Search failed');
      setResults(data.results as SearchResult[]);
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : 'Search failed');
      setResults(null);
    } finally {
      setSearching(false);
    }
  };

  const addResult = async (result: SearchResult) => {
    setSearchError(null);
    try {
      const info: LocationInfo = {
        name: result.name,
        title: result.title,
        description: result.description,
        member_count: result.member_count,
        active_count: result.active_count,
        is_nsfw: result.is_nsfw,
      };
      const created = (await postJson(base, { name: result.name, location_info: info })) as {
        id: number;
        status: string;
      };
      setResults((prev) =>
        prev
          ? prev.map((r) =>
              r.name === result.name
                ? { ...r, candidate_id: created.id, candidate_status: created.status }
                : r,
            )
          : prev,
      );
      await fetchCandidates(true);
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : 'Could not add location');
    }
  };

  const trialBlocked = isActiveTrial(runningTrial);

  return (
    <div className="space-y-4">
      {/* Keyword search: always usable, including when the list is empty */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Search className="h-4 w-4" />
            Find communities
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              search();
            }}
          >
            <Input
              aria-label="Search communities"
              placeholder="Keyword, e.g. rope personals"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <Button type="submit" disabled={searching || !query.trim()}>
              {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Search'}
            </Button>
          </form>
          {searchError && <p className="text-sm text-destructive">{searchError}</p>}
          {results && results.length === 0 && (
            <p className="text-sm text-muted-foreground">No communities found.</p>
          )}
          {results && results.length > 0 && (
            <ul className="divide-y">
              {results.map((r) => (
                <li key={r.name} className="flex items-start justify-between gap-3 py-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm">{r.name}</span>
                      {r.is_nsfw && <Badge variant="outline">NSFW</Badge>}
                      <span className="text-xs text-muted-foreground">
                        {formatCount(r.member_count)} members
                      </span>
                    </div>
                    {r.description && (
                      <p className="text-xs text-muted-foreground line-clamp-2">{r.description}</p>
                    )}
                  </div>
                  {r.watched ? (
                    <Badge variant="secondary">Watched</Badge>
                  ) : r.candidate_id ? (
                    <Badge variant="secondary">Candidate ({r.candidate_status})</Badge>
                  ) : (
                    <Button size="sm" variant="outline" onClick={() => addResult(r)}>
                      <Plus className="h-3.5 w-3.5 mr-1" />
                      Add
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Candidate list */}
      <div className="flex items-center justify-between">
        <div className="flex gap-1" role="group" aria-label="Candidate view">
          {(['open', 'dismissed', 'accepted'] as View[]).map((v) => (
            <Button
              key={v}
              size="sm"
              variant={view === v ? 'default' : 'ghost'}
              onClick={() => setView(v)}
            >
              {v === 'open' ? 'Candidates' : v[0].toUpperCase() + v.slice(1)}
            </Button>
          ))}
        </div>
        <Button variant="outline" size="sm" onClick={() => fetchCandidates()}>
          <RefreshCw className="h-4 w-4 mr-1" />
          Refresh
        </Button>
      </div>

      {actionError && (
        <div className="p-3 rounded-md bg-destructive/10 text-destructive text-sm flex items-center gap-2">
          <AlertCircle className="h-4 w-4" />
          {actionError}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center h-32" aria-label="Loading candidates">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : error ? (
        <Card className="p-8">
          <div className="text-center">
            <AlertCircle className="h-10 w-10 text-destructive mx-auto mb-3" />
            <p className="text-destructive font-medium">{error}</p>
            <Button variant="outline" onClick={() => fetchCandidates()} className="mt-4">
              Try Again
            </Button>
          </div>
        </Card>
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-10 text-center">
            <Compass className="h-10 w-10 text-muted-foreground/50 mb-3" />
            <h3 className="font-medium mb-1">
              {view === 'open' ? 'No candidate sources yet' : `No ${view} candidates`}
            </h3>
            {view === 'open' && (
              <p className="text-muted-foreground text-sm max-w-md">
                Candidates appear once enough analysed authors exist: a community is proposed
                when several authors you rated suitable, contacted, or engaged also post there.
                Mining runs daily. You can search for communities above in the meantime.
              </p>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">{total} candidates, highest lift first</p>
          {items.map((c) => {
            const busy = busyId === c.id;
            const activeTrial = isActiveTrial(c.latest_trial);
            return (
              <Card key={c.id} data-testid={`candidate-${c.id}`}>
                <CardContent className="p-4 space-y-2">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="font-medium">{c.name}</h3>
                        <Badge variant="outline">
                          {c.kind === 'location' ? 'Community' : 'External site'}
                        </Badge>
                        {c.origin === 'manual' && <Badge variant="outline">Manual</Badge>}
                        {c.status !== 'new' && <Badge variant="secondary">{c.status}</Badge>}
                        {c.location_info?.is_nsfw && <Badge variant="outline">NSFW</Badge>}
                        {c.lift !== null && (
                          <span className="text-sm font-semibold tabular-nums">
                            lift {c.lift.toFixed(2)}×
                          </span>
                        )}
                      </div>
                      <Evidence candidate={c} />
                      <LocationDetails candidate={c} />
                    </div>

                    <div className="flex flex-wrap justify-end gap-1.5 shrink-0">
                      {c.status === 'dismissed' ? (
                        <Button size="sm" variant="outline" onClick={() => restore(c)} disabled={busy}>
                          <RotateCcw className="h-3.5 w-3.5 mr-1" />
                          Restore
                        </Button>
                      ) : c.status === 'accepted' ? null : (
                        <>
                          {c.kind === 'location' && (
                            <>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => trial(c)}
                                disabled={busy || trialBlocked}
                                title={trialBlocked ? 'Another trial is running' : undefined}
                              >
                                <FlaskConical className="h-3.5 w-3.5 mr-1" />
                                {c.latest_trial ? 'Re-run trial' : 'Run trial'}
                              </Button>
                              <Button
                                size="sm"
                                onClick={() => onCreateWatch(c)}
                                disabled={busy || activeTrial}
                              >
                                <Plus className="h-3.5 w-3.5 mr-1" />
                                Create watch
                              </Button>
                            </>
                          )}
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => snooze(c)}
                            disabled={busy || activeTrial}
                          >
                            <BellOff className="h-3.5 w-3.5 mr-1" />
                            Snooze {SNOOZE_DAYS}d
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => dismiss(c)}
                            disabled={busy || activeTrial}
                          >
                            <X className="h-3.5 w-3.5 mr-1" />
                            Dismiss
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                  {c.latest_trial && (
                    <TrialSummary
                      trial={c.latest_trial}
                      busy={busy}
                      onCancel={() => cancelTrial(c, c.latest_trial as SourceTrial)}
                    />
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
