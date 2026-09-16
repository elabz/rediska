'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Loader2,
  Play,
  XCircle,
  AlertCircle,
  CheckCircle,
  MinusCircle,
  RefreshCw,
  FlaskConical,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/EmptyState';
import { cn } from '@/lib/utils';
import { formatAgreement } from '@/lib/evaluations';

// =============================================================================
// Types (mirror api/schemas/evaluations.py Replay*)
// =============================================================================

interface ReplayCaseResult {
  evaluation_id: number;
  subject_type: string;
  subject_id: number;
  agreed: boolean | null;
  skipped: string | null;
  expected: Record<string, unknown> | null;
  produced: Record<string, unknown> | null;
  field_results: Record<string, boolean>;
  error: string | null;
}

export interface Replay {
  id: number;
  dimension: string;
  candidate_version: number | null;
  candidate_system_prompt: string | null;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  case_count: number;
  completed_count: number;
  agreed_count: number;
  skipped_no_input: number;
  agreement: number | null;
  results: ReplayCaseResult[];
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

interface ReplayPanelProps {
  dimension: string;
  /** Current editor text — replayed as the draft. */
  draftSystemPrompt: string;
  draftTemperature?: number;
  draftMaxTokens?: number;
  activeVersion: number;
}

const POLL_MS = 2000;

const STATUS_STYLE: Record<Replay['status'], string> = {
  queued: 'bg-muted text-muted-foreground',
  running: 'bg-blue-500/10 text-blue-700 border-blue-500/30 dark:text-blue-300',
  completed: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/30 dark:text-emerald-300',
  failed: 'bg-red-500/10 text-red-700 border-red-500/30 dark:text-red-300',
  cancelled: 'bg-amber-500/10 text-amber-700 border-amber-500/30 dark:text-amber-300',
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function fmt(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (Array.isArray(value)) return value.length ? value.map(String).join(', ') : '—';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function errorMessage(data: unknown, fallback: string): string {
  if (data && typeof data === 'object' && 'detail' in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      return detail.map((e: { msg?: string }) => e.msg || 'Validation error').join(', ');
    }
  }
  return fallback;
}

// =============================================================================
// Per-case results table
// =============================================================================

function CaseTable({ results }: { results: ReplayCaseResult[] }) {
  if (results.length === 0) {
    return <p className="text-xs text-muted-foreground">No cases processed yet.</p>;
  }
  const fields = Array.from(
    new Set(results.flatMap((r) => Object.keys(r.field_results || {})))
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-muted-foreground">
            <th className="p-1 font-normal">Case</th>
            <th className="p-1 font-normal">Result</th>
            {fields.map((f) => (
              <th key={f} className="p-1 font-normal">{f.replace(/_/g, ' ')}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {results.map((r) => (
            <tr key={r.evaluation_id} className="border-t border-border/50 align-top">
              <td className="p-1 whitespace-nowrap">
                <span className="font-mono">#{r.evaluation_id}</span>
                <div className="text-[10px] text-muted-foreground">
                  {r.subject_type === 'lead_analysis' ? 'analysis' : 'scout'} {r.subject_id}
                </div>
              </td>
              <td className="p-1 whitespace-nowrap">
                {r.skipped ? (
                  <Badge variant="outline" className="font-normal text-muted-foreground">
                    <MinusCircle className="h-3 w-3 mr-1" />
                    skipped ({r.skipped.replace(/_/g, ' ')})
                  </Badge>
                ) : r.agreed ? (
                  <Badge variant="outline" className="font-normal bg-emerald-500/10 text-emerald-700 border-emerald-500/30 dark:text-emerald-300">
                    <CheckCircle className="h-3 w-3 mr-1" />
                    agree
                  </Badge>
                ) : (
                  <Badge variant="outline" className="font-normal bg-red-500/10 text-red-700 border-red-500/30 dark:text-red-300">
                    <XCircle className="h-3 w-3 mr-1" />
                    disagree
                  </Badge>
                )}
                {r.error && <div className="text-[10px] text-destructive mt-0.5 max-w-[200px] truncate" title={r.error}>{r.error}</div>}
              </td>
              {fields.map((f) => {
                const ok = r.field_results?.[f];
                if (ok === undefined) return <td key={f} className="p-1 text-muted-foreground">—</td>;
                return (
                  <td key={f} className={cn('p-1', ok ? 'text-emerald-700 dark:text-emerald-300' : 'text-red-700 dark:text-red-300')}>
                    <div className="text-[10px] text-muted-foreground">expected</div>
                    <div className="max-w-[180px] truncate" title={fmt(r.expected?.[f])}>{fmt(r.expected?.[f])}</div>
                    <div className="text-[10px] text-muted-foreground mt-0.5">produced</div>
                    <div className="max-w-[180px] truncate" title={fmt(r.produced?.[f])}>{fmt(r.produced?.[f])}</div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// =============================================================================
// Panel
// =============================================================================

export function ReplayPanel({
  dimension,
  draftSystemPrompt,
  draftTemperature,
  draftMaxTokens,
  activeVersion,
}: ReplayPanelProps) {
  const [replays, setReplays] = useState<Replay[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState<number | null>(null);
  const [selected, setSelected] = useState<Replay | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchReplays = useCallback(async () => {
    try {
      const response = await fetch(`/api/core/agent-prompts/${dimension}/replays`, { credentials: 'include' });
      const data = await response.json();
      if (!response.ok) throw new Error(errorMessage(data, 'Failed to load replays'));
      setReplays(data.replays || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load replays');
    } finally {
      setLoading(false);
    }
  }, [dimension]);

  const fetchDetail = useCallback(
    async (id: number) => {
      try {
        const response = await fetch(`/api/core/agent-prompts/${dimension}/replays/${id}`, { credentials: 'include' });
        const data = await response.json();
        if (!response.ok) throw new Error(errorMessage(data, 'Failed to load replay'));
        setSelected(data as Replay);
        setReplays((prev) => prev.map((r) => (r.id === id ? { ...r, ...data, results: [] } : r)));
        return data as Replay;
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load replay');
        return null;
      }
    },
    [dimension]
  );

  useEffect(() => {
    setLoading(true);
    setSelected(null);
    setExpandedId(null);
    fetchReplays();
  }, [fetchReplays]);

  // Poll the expanded replay while it is queued/running
  useEffect(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    const active = selected && (selected.status === 'queued' || selected.status === 'running');
    if (!active || !selected) return;
    pollRef.current = setInterval(async () => {
      const latest = await fetchDetail(selected.id);
      if (latest && latest.status !== 'queued' && latest.status !== 'running') {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        fetchReplays();
      }
    }, POLL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [selected, fetchDetail, fetchReplays]);

  const startReplay = async () => {
    setStarting(true);
    setError(null);
    try {
      const response = await fetch(`/api/core/agent-prompts/${dimension}/replay`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          system_prompt: draftSystemPrompt,
          temperature: draftTemperature,
          max_tokens: draftMaxTokens,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(errorMessage(data, 'Failed to start replay'));
      await fetchReplays();
      setExpandedId(data.id);
      await fetchDetail(data.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start replay');
    } finally {
      setStarting(false);
    }
  };

  const cancelReplay = async (id: number) => {
    setCancelling(id);
    try {
      const response = await fetch(`/api/core/agent-prompts/${dimension}/replays/${id}/cancel`, {
        method: 'POST',
        credentials: 'include',
      });
      const data = await response.json();
      if (!response.ok) throw new Error(errorMessage(data, 'Failed to cancel replay'));
      await fetchReplays();
      if (selected?.id === id) await fetchDetail(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel replay');
    } finally {
      setCancelling(null);
    }
  };

  const toggle = async (id: number) => {
    if (expandedId === id) {
      setExpandedId(null);
      setSelected(null);
      return;
    }
    setExpandedId(id);
    await fetchDetail(id);
  };

  const inFlight = replays.some((r) => r.status === 'queued' || r.status === 'running');
  const isDimensionAgent = dimension !== 'meta_analysis' && dimension !== 'scout_quick_analysis';

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="text-base flex items-center gap-2">
                <FlaskConical className="h-4 w-4 text-purple-500" />
                Replay against labelled cases
              </CardTitle>
              <CardDescription>
                Runs the current editor text on the cases you have evaluated for this dimension and
                reports agreement with your labels. Nothing is saved or activated.
              </CardDescription>
            </div>
            <Button onClick={startReplay} disabled={starting || inFlight || !isDimensionAgent || !draftSystemPrompt.trim()}>
              {starting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Play className="h-4 w-4 mr-2" />}
              Replay draft
            </Button>
          </div>
        </CardHeader>
        {!isDimensionAgent && (
          <CardContent className="pt-0">
            <p className="text-xs text-muted-foreground">
              Replay is available for the five dimension agents only.
            </p>
          </CardContent>
        )}
        {error && (
          <CardContent className="pt-0">
            <div className="flex items-center gap-2 rounded-md border border-destructive bg-destructive/10 p-2 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          </CardContent>
        )}
      </Card>

      {/* History */}
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium">Replay history</h4>
        <Button variant="ghost" size="sm" onClick={fetchReplays} disabled={loading}>
          <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
        </Button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : replays.length === 0 ? (
        <EmptyState
          icon={<FlaskConical className="h-8 w-8" />}
          title="No replays yet"
          description="Evaluate some analyses for this dimension in the Review queue, edit the prompt, then replay the draft to see whether agreement improves before you save it."
          className="py-8"
        />
      ) : (
        <div className="space-y-2">
          {replays.map((r) => {
            const expanded = expandedId === r.id;
            const detail = expanded && selected?.id === r.id ? selected : r;
            const progress = detail.case_count ? Math.round((detail.completed_count / detail.case_count) * 100) : 0;
            return (
              <div key={r.id} className={cn('rounded-lg border', expanded && 'border-primary/50')}>
                <button className="w-full p-3 text-left" onClick={() => toggle(r.id)}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <Badge variant="outline" className={cn('text-xs', STATUS_STYLE[detail.status])}>
                        {(detail.status === 'running' || detail.status === 'queued') && (
                          <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                        )}
                        {detail.status}
                      </Badge>
                      <span className="font-medium">
                        {detail.candidate_version ? `v${detail.candidate_version}` : 'draft'}
                      </span>
                      <span className="text-muted-foreground">{formatDate(detail.created_at)}</span>
                      <span className="text-muted-foreground">
                        {detail.completed_count}/{detail.case_count} cases
                        {detail.skipped_no_input ? ` · ${detail.skipped_no_input} skipped` : ''}
                      </span>
                      <span className="font-semibold">{formatAgreement(detail.agreement)}</span>
                      <span className="text-[10px] text-muted-foreground">vs active v{activeVersion}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      {(detail.status === 'queued' || detail.status === 'running') && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7"
                          disabled={cancelling === r.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            cancelReplay(r.id);
                          }}
                        >
                          {cancelling === r.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <XCircle className="h-3.5 w-3.5 mr-1" />}
                          Cancel
                        </Button>
                      )}
                      {expanded ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
                    </div>
                  </div>
                  {(detail.status === 'running' || detail.status === 'queued') && (
                    <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                      <div className="h-full bg-blue-500 transition-all" style={{ width: `${progress}%` }} />
                    </div>
                  )}
                </button>
                {expanded && (
                  <div className="border-t p-3 space-y-3">
                    {detail.error && (
                      <div className="text-xs text-destructive">{detail.error}</div>
                    )}
                    {selected?.id === r.id ? (
                      <CaseTable results={selected.results} />
                    ) : (
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Loader2 className="h-3 w-3 animate-spin" /> Loading cases…
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
