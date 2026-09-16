'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  Loader2,
  RefreshCw,
  SkipForward,
  AlertCircle,
  CheckCircle,
  XCircle,
  AlertTriangle,
  ExternalLink,
  Inbox,
  ShieldAlert,
  CalendarDays,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { EmptyState } from '@/components/EmptyState';
import { MarkdownText } from '@/components/ui/markdown-text';
import { EvaluationControl } from '@/components/evaluations/EvaluationControl';
import { AgentInputSections } from '@/components/evaluations/AgentInputSections';
import { cn } from '@/lib/utils';
import {
  DIMENSION_LABELS,
  EVALUABLE_DIMENSIONS,
  RECOMMENDATION_LABELS,
  type EffectiveEvaluation,
  type EvaluableDimension,
  type EvaluationMap,
  type ModelInput,
  type Recommendation,
  type SubjectType,
} from '@/lib/evaluations';

// =============================================================================
// Types (mirror api/schemas/evaluations.py QueueItem)
// =============================================================================

interface GateResult {
  gate: string;
  status: string;
  reason: string;
}

export interface QueueItem {
  subject_type: SubjectType;
  subject_id: number;
  reason: string;
  recommendation: Recommendation | null;
  confidence: number | null;
  gate_results: GateResult[];
  unclear_gate_count: number;
  failed_gate_count: number;
  lead_id: number | null;
  lead_status: string | null;
  analysis_id: number | null;
  scout_post_id: number | null;
  watch_id: number | null;
  account_id: number | null;
  author: string | null;
  title: string | null;
  body: string | null;
  post_url: string | null;
  interests_summary: string | null;
  character_summary: string | null;
  reasoning: string | null;
  dimensions: Record<string, Record<string, unknown>>;
  meta_analysis: Record<string, unknown> | null;
  prompt_versions: Record<string, number>;
  analyzed_at: string | null;
  posted_at: string | null;
  posted_at_kind: 'posted' | 'first_seen' | null;
  evaluations: EvaluationMap;
  model_inputs: Record<string, ModelInput>;
}

interface QueueResponse {
  items: QueueItem[];
  next_cursor: string | null;
  total_remaining: number;
}

const REASON_LABELS: Record<string, { label: string; className: string }> = {
  contradiction_ignored_suitable: {
    label: 'Contradiction: suitable but archived',
    className: 'bg-purple-500/10 text-purple-700 border-purple-500/30 dark:text-purple-300',
  },
  contradiction_promoted_not_suitable: {
    label: 'Contradiction: promoted despite verdict',
    className: 'bg-purple-500/10 text-purple-700 border-purple-500/30 dark:text-purple-300',
  },
  sample: { label: 'Sample', className: 'bg-muted text-muted-foreground' },
};

const REC_ICON: Record<string, React.ReactNode> = {
  suitable: <CheckCircle className="h-4 w-4 text-emerald-500" />,
  not_recommended: <XCircle className="h-4 w-4 text-red-500" />,
  needs_review: <AlertTriangle className="h-4 w-4 text-amber-500" />,
};

const GATE_STYLE: Record<string, string> = {
  pass: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/30 dark:text-emerald-300',
  unclear: 'bg-amber-500/10 text-amber-700 border-amber-500/30 dark:text-amber-300',
  fail: 'bg-red-500/10 text-red-700 border-red-500/30 dark:text-red-300',
};

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (Array.isArray(value)) return value.length ? value.map(String).join(', ') : '—';
  if (typeof value === 'object') return JSON.stringify(value);
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  return String(value);
}

// Fields worth showing per dimension in the queue card (kept short on purpose).
const DIMENSION_PREVIEW: Record<string, string[]> = {
  demographics: ['age', 'gender', 'location', 'location_state'],
  preferences: ['kinks', 'hobbies', 'compatibility_score'],
  relationship_goals: ['relationship_intent', 'partner_max_age', 'deal_breakers'],
  risk_flags: ['is_authentic', 'red_flags', 'scam_indicators'],
  sexual_preferences: ['ds_orientation', 'kinks_interests'],
};

function formatAge(iso: string | null): string {
  if (!iso) return '—';
  const diffMs = Date.now() - new Date(iso).getTime();
  const days = Math.floor(diffMs / 86400000);
  if (days < 1) return 'today';
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

// =============================================================================
// Queue item card
// =============================================================================

function QueueItemCard({
  item,
  onEvaluated,
  onSkip,
}: {
  item: QueueItem;
  onEvaluated: (key: string, saved: EffectiveEvaluation) => void;
  onSkip: () => void;
}) {
  const reason = REASON_LABELS[item.reason] ?? REASON_LABELS.sample;
  const nonPassing = item.gate_results.filter((g) => g.status !== 'pass');
  const inputs = item.model_inputs || {};
  const inputDims = EVALUABLE_DIMENSIONS.filter((d) => inputs[d]);
  // Final-verdict evaluation gets the richest input as context
  const richestDim = inputDims.reduce(
    (best, d) => ((inputs[d]?.total_chars ?? 0) > (inputs[best]?.total_chars ?? 0) ? d : best),
    inputDims[0] ?? 'demographics'
  );
  const richestInput = inputs[richestDim] ?? null;
  const postedLabel = item.posted_at
    ? `${item.posted_at_kind === 'first_seen' ? 'First seen' : 'Posted'} ${formatDateTime(item.posted_at)} (${formatAge(item.posted_at)})`
    : 'Post date unknown';

  return (
    <Card className="border-2">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              {item.recommendation && REC_ICON[item.recommendation]}
              <CardTitle className="text-base">
                {item.recommendation ? RECOMMENDATION_LABELS[item.recommendation] : 'No verdict'}
              </CardTitle>
              {item.confidence !== null && (
                <Badge variant="secondary">{Math.round(item.confidence * 100)}% score</Badge>
              )}
              <Badge variant="outline" className={cn('text-xs', reason.className)}>
                {item.reason.startsWith('contradiction') && <ShieldAlert className="h-3 w-3 mr-1" />}
                {reason.label}
              </Badge>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span
                className={cn(
                  'inline-flex items-center gap-1 font-medium',
                  item.posted_at && Date.now() - new Date(item.posted_at).getTime() > 90 * 86400000
                    ? 'text-amber-700 dark:text-amber-300'
                    : 'text-foreground'
                )}
                title={item.posted_at ?? undefined}
              >
                <CalendarDays className="h-3.5 w-3.5" />
                {postedLabel}
              </span>
              {item.analyzed_at && <span>· analysed {formatAge(item.analyzed_at)}</span>}
              <span>· {item.subject_type === 'lead_analysis' ? `Lead analysis #${item.subject_id}` : `Scout post #${item.subject_id}`}</span>
              {item.author && <span>u/{item.author}</span>}
              {item.lead_id && (
                <Link href={`/leads/${item.lead_id}`} className="text-blue-500 hover:underline">
                  Lead #{item.lead_id}
                  {item.lead_status ? ` (${item.lead_status})` : ''}
                </Link>
              )}
              {item.watch_id && (
                <Link href={`/settings/scout-watches/${item.watch_id}/history`} className="text-blue-500 hover:underline">
                  Watch #{item.watch_id}
                </Link>
              )}
              {item.post_url && (
                <a href={item.post_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-blue-500 hover:underline">
                  <ExternalLink className="h-3 w-3" /> Source
                </a>
              )}
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={onSkip}>
            <SkipForward className="h-4 w-4 mr-1" />
            Skip
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Gates: exactly why it is here */}
        <div className="flex flex-wrap gap-1.5">
          {item.gate_results.length === 0 && (
            <span className="text-xs text-muted-foreground">No gate results stored.</span>
          )}
          {item.gate_results.map((g) => (
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

        {/* Final verdict control */}
        <div className="flex items-center justify-between gap-2 rounded-lg border border-dashed p-2">
          <span className="text-xs font-medium uppercase text-muted-foreground">Final verdict</span>
          <EvaluationControl
            subjectType={item.subject_type}
            subjectId={item.subject_id}
            dimension={null}
            evaluation={null}
            agentRecommendation={item.recommendation}
            modelInput={richestInput}
            onSaved={(saved) => onEvaluated('final', saved)}
          />
        </div>

        {/* Everything the agents received, as readable sections (union across agents) */}
        {inputDims.length > 0 ? (
          <AgentInputSections inputs={inputs} defaultOpen />
        ) : (
          <div className="space-y-2">
            {item.title && <h4 className="font-medium text-sm">{item.title}</h4>}
            {item.body ? (
              <div className="text-sm whitespace-pre-wrap bg-muted/30 p-3 rounded max-h-64 overflow-y-auto">
                {item.body}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">No post body stored.</p>
            )}
            {item.interests_summary && (
              <div className="rounded-md bg-muted/30 p-3">
                <div className="text-[10px] font-medium uppercase text-muted-foreground mb-1">Interests</div>
                <MarkdownText className="text-xs">{item.interests_summary}</MarkdownText>
              </div>
            )}
            {item.character_summary && (
              <div className="rounded-md bg-muted/30 p-3">
                <div className="text-[10px] font-medium uppercase text-muted-foreground mb-1">Character</div>
                <MarkdownText className="text-xs">{item.character_summary}</MarkdownText>
              </div>
            )}
          </div>
        )}

        {/* Reasoning */}
        {item.reasoning && (
          <div className="rounded-md bg-muted/30 p-3">
            <div className="text-[10px] font-medium uppercase text-muted-foreground mb-1">Agent reasoning</div>
            <MarkdownText className="text-xs">{item.reasoning}</MarkdownText>
          </div>
        )}

        {/* Dimensions with per-dimension controls */}
        <div className="grid gap-3 md:grid-cols-2">
          {EVALUABLE_DIMENSIONS.map((dim) => {
            const output = item.dimensions[dim];
            const errored = output && typeof output.error === 'string' && Object.keys(output).length === 1;
            const preview = DIMENSION_PREVIEW[dim] ?? [];
            return (
              <div key={dim} className="rounded-md border p-2 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium">{DIMENSION_LABELS[dim]}</span>
                  <EvaluationControl
                    subjectType={item.subject_type}
                    subjectId={item.subject_id}
                    dimension={dim as EvaluableDimension}
                    evaluation={item.evaluations?.[dim] ?? null}
                    agentOutput={errored ? null : output}
                    modelInput={inputs[dim] ?? null}
                    onSaved={(saved) => onEvaluated(dim, saved)}
                    size="xs"
                  />
                </div>
                {errored ? (
                  <p className="text-xs text-destructive">{String(output.error)}</p>
                ) : output ? (
                  <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-xs">
                    {preview
                      .filter((k) => output[k] !== undefined)
                      .map((k) => (
                        <div key={k} className="contents">
                          <dt className="text-muted-foreground">{k.replace(/_/g, ' ')}</dt>
                          <dd className="truncate" title={formatValue(output[k])}>
                            {formatValue(output[k])}
                          </dd>
                        </div>
                      ))}
                  </dl>
                ) : (
                  <p className="text-xs text-muted-foreground">No output.</p>
                )}
              </div>
            );
          })}
        </div>

        {Object.keys(item.prompt_versions).length > 0 && (
          <div className="text-[10px] text-muted-foreground">
            Prompt versions:{' '}
            {Object.entries(item.prompt_versions)
              .filter(([k]) => !k.startsWith('_'))
              .map(([k, v]) => `${k} v${v}`)
              .join(' · ')}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// =============================================================================
// Review queue: list of analyses waiting for evaluation + detail pane
// =============================================================================

const PAGE_SIZE = 25;


function itemKey(item: QueueItem): string {
  return `${item.subject_type}-${item.subject_id}`;
}

function QueueListRow({
  item,
  selected,
  onSelect,
}: {
  item: QueueItem;
  selected: boolean;
  onSelect: () => void;
}) {
  const evaluatedDims = Object.values(item.evaluations || {}).filter(Boolean).length;
  const reason = REASON_LABELS[item.reason] ?? REASON_LABELS.sample;
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'w-full text-left px-3 py-2 border-b border-border/60 last:border-b-0 hover:bg-muted/50 transition-colors',
        selected && 'bg-primary/5 border-l-2 border-l-primary'
      )}
      aria-current={selected ? 'true' : undefined}
    >
      <div className="flex items-center gap-2">
        {item.recommendation && REC_ICON[item.recommendation]}
        <span className="text-sm font-medium truncate flex-1">{item.title || `#${item.subject_id}`}</span>
        <span
          className={cn(
            'text-[10px] whitespace-nowrap',
            item.posted_at && Date.now() - new Date(item.posted_at).getTime() > 90 * 86400000
              ? 'text-amber-600'
              : 'text-muted-foreground'
          )}
          title={item.posted_at ? `${item.posted_at_kind === 'first_seen' ? 'First seen' : 'Posted'} ${formatDateTime(item.posted_at)}` : 'Post date unknown'}
        >
          {item.posted_at ? formatAge(item.posted_at) : '—'}
        </span>
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
        {item.author && <span>u/{item.author}</span>}
        {item.confidence !== null && <span>{Math.round(item.confidence * 100)}%</span>}
        {item.reason !== 'sample' && (
          <Badge variant="outline" className={cn('text-[10px] px-1 py-0 font-normal', reason.className)}>
            contradiction
          </Badge>
        )}
        {item.failed_gate_count > 0 && <span className="text-red-600">{item.failed_gate_count} failed</span>}
        {item.unclear_gate_count > 0 && <span className="text-amber-600">{item.unclear_gate_count} unclear</span>}
        {evaluatedDims > 0 && <span className="text-emerald-600">{evaluatedDims}/5 dims judged</span>}
      </div>
    </button>
  );
}

export function ReviewQueue() {
  const [items, setItems] = useState<QueueItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [totalRemaining, setTotalRemaining] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  // Filters
  const [recommendation, setRecommendation] = useState<string>('all');
  const [dimensionFailed, setDimensionFailed] = useState<string>('any');
  const [watchId, setWatchId] = useState<string>('');
  const [since, setSince] = useState<string>('');
  const [sort, setSort] = useState<'newest' | 'stratified'>('newest');

  const buildQuery = useCallback(
    (cursor?: string | null) => {
      const params = new URLSearchParams();
      params.set('limit', String(PAGE_SIZE));
      params.set('sort', sort);
      if (recommendation !== 'all') params.set('recommendation', recommendation);
      if (dimensionFailed !== 'any') params.set('dimension_failed', dimensionFailed);
      if (watchId.trim()) params.set('watch_id', watchId.trim());
      if (since) params.set('since', new Date(since).toISOString());
      if (cursor) params.set('cursor', cursor);
      return params.toString();
    },
    [recommendation, dimensionFailed, watchId, since, sort]
  );

  const fetchQueue = useCallback(
    async (cursor?: string | null, append = false) => {
      if (append) setLoadingMore(true);
      else setLoading(true);
      setError(null);
      try {
        const response = await fetch(`/api/core/evaluations/queue?${buildQuery(cursor)}`, {
          credentials: 'include',
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(typeof data.detail === 'string' ? data.detail : 'Failed to load the review queue');
        }
        const res = data as QueueResponse;
        setItems((prev) => (append ? [...prev, ...res.items] : res.items));
        setNextCursor(res.next_cursor);
        setTotalRemaining(res.total_remaining);
        if (!append) setSelectedKey(res.items[0] ? itemKey(res.items[0]) : null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load the review queue');
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [buildQuery]
  );

  useEffect(() => {
    fetchQueue();
  }, [fetchQueue]);

  const selectedIndex = items.findIndex((i) => itemKey(i) === selectedKey);
  const current = selectedIndex >= 0 ? items[selectedIndex] : null;

  const selectNext = (fromIndex: number, remaining: QueueItem[]) => {
    const next = remaining[fromIndex] ?? remaining[fromIndex - 1] ?? null;
    setSelectedKey(next ? itemKey(next) : null);
  };

  const skip = () => {
    if (selectedIndex < 0) return;
    const next = items[selectedIndex + 1] ?? items[0] ?? null;
    setSelectedKey(next && next !== current ? itemKey(next) : null);
  };

  const handleEvaluated = (key: string, saved: EffectiveEvaluation) => {
    if (selectedIndex < 0) return;
    if (key === 'final') {
      // A final verdict removes the item from the queue; move to the next one.
      const remaining = items.filter((_, idx) => idx !== selectedIndex);
      setItems(remaining);
      setTotalRemaining((n) => Math.max(0, n - 1));
      selectNext(selectedIndex, remaining);
      return;
    }
    setItems((prev) =>
      prev.map((it, idx) =>
        idx === selectedIndex ? { ...it, evaluations: { ...(it.evaluations || {}), [key]: saved } } : it
      )
    );
  };

  return (
    <div className="space-y-4">
      {/* Filters */}
      <Card>
        <CardContent className="pt-4">
          <div className="grid gap-3 md:grid-cols-6 items-end">
            <div className="space-y-1">
              <Label className="text-xs">Order</Label>
              <Select value={sort} onValueChange={(v) => setSort(v as 'newest' | 'stratified')}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="newest">Newest first</SelectItem>
                  <SelectItem value="stratified">Mix classes evenly</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Recommendation</Label>
              <Select value={recommendation} onValueChange={setRecommendation}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All classes</SelectItem>
                  <SelectItem value="suitable">Suitable</SelectItem>
                  <SelectItem value="needs_review">Needs review</SelectItem>
                  <SelectItem value="not_recommended">Not recommended</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Dimension failed</Label>
              <Select value={dimensionFailed} onValueChange={setDimensionFailed}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="any">Any</SelectItem>
                  {EVALUABLE_DIMENSIONS.map((d) => (
                    <SelectItem key={d} value={d}>
                      {DIMENSION_LABELS[d]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="q-watch" className="text-xs">Watch id</Label>
              <Input id="q-watch" value={watchId} onChange={(e) => setWatchId(e.target.value)} placeholder="any" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="q-since" className="text-xs">Analysed since</Label>
              <Input id="q-since" type="date" value={since} onChange={(e) => setSince(e.target.value)} />
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground">{totalRemaining} waiting</span>
              <Button variant="outline" size="sm" onClick={() => fetchQueue()} disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Body */}
      {error ? (
        <Card className="p-6">
          <div className="flex items-center gap-2 text-destructive">
            <AlertCircle className="h-5 w-5" />
            <span className="text-sm">{error}</span>
          </div>
          <Button variant="outline" size="sm" className="mt-3" onClick={() => fetchQueue()}>
            Try again
          </Button>
        </Card>
      ) : loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Inbox className="h-8 w-8" />}
            title="Nothing waiting for review"
            description="Every analysed lead and scout post matching these filters has a final verdict. New items arrive as scout watches analyse posts and as leads are re-analysed; recent contradictions (a suitable lead you archived, a rejected post you promoted) are served first."
            action={
              <Button variant="outline" size="sm" onClick={() => fetchQueue()}>
                <RefreshCw className="h-4 w-4 mr-1" />
                Check again
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(260px,1fr)_minmax(0,2.2fr)]">
          {/* List of analyses waiting for evaluation */}
          <Card className="overflow-hidden self-start lg:sticky lg:top-4">
            <CardHeader className="py-2 px-3 border-b">
              <CardTitle className="text-xs font-medium uppercase text-muted-foreground">
                Waiting for evaluation · showing {items.length} of {totalRemaining}
              </CardTitle>
            </CardHeader>
            <div className="max-h-[70vh] overflow-y-auto">
              {items.map((it) => (
                <QueueListRow
                  key={itemKey(it)}
                  item={it}
                  selected={itemKey(it) === selectedKey}
                  onSelect={() => setSelectedKey(itemKey(it))}
                />
              ))}
              {nextCursor && (
                <div className="p-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="w-full"
                    onClick={() => fetchQueue(nextCursor, true)}
                    disabled={loadingMore}
                  >
                    {loadingMore ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Load more'}
                  </Button>
                </div>
              )}
            </div>
          </Card>

          {/* Detail */}
          <div className="min-w-0">
            {current ? (
              <QueueItemCard key={itemKey(current)} item={current} onEvaluated={handleEvaluated} onSkip={skip} />
            ) : (
              <Card className="p-6 text-sm text-muted-foreground">Select an analysis from the list.</Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
