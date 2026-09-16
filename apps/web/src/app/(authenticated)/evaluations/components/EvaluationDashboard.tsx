'use client';

import { useCallback, useEffect, useState } from 'react';
import { Loader2, RefreshCw, AlertCircle, BarChart3, ListChecks } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components/EmptyState';
import { cn } from '@/lib/utils';
import {
  DIMENSION_LABELS,
  REASON_TAG_LABELS,
  RECOMMENDATIONS,
  RECOMMENDATION_LABELS,
  formatAgreement,
  type ReasonTag,
} from '@/lib/evaluations';

// =============================================================================
// Types (mirror api/schemas/evaluations.py EvaluationSummary)
// =============================================================================

interface VerdictCounts {
  agree: number;
  partial: number;
  disagree: number;
  total: number;
  agreement: number | null;
}

interface DimensionSummary {
  dimension: string;
  counts: VerdictCounts;
  tags: Record<string, number>;
  by_prompt_version: Record<string, VerdictCounts>;
}

interface TrendPoint {
  week: string;
  dimension: string;
  counts: VerdictCounts;
}

interface MissingInfoItem {
  text: string;
  count: number;
  dimensions: string[];
}

export interface EvaluationSummary {
  total_evaluations: number;
  overall: VerdictCounts;
  dimensions: DimensionSummary[];
  confusion_matrix: Record<string, Record<string, number>>;
  trend: TrendPoint[];
  missing_info: MissingInfoItem[];
}

// =============================================================================
// Small visual pieces (no chart library; bars are plain divs)
// =============================================================================

function agreementColor(value: number | null): string {
  if (value === null) return 'bg-muted';
  if (value >= 0.8) return 'bg-emerald-500';
  if (value >= 0.6) return 'bg-amber-500';
  return 'bg-red-500';
}

function AgreementBar({ counts, label }: { counts: VerdictCounts; label: string }) {
  const { agree, partial, disagree, total, agreement } = counts;
  const pct = (n: number) => (total ? `${(n / total) * 100}%` : '0%');
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground">
          {formatAgreement(agreement)} · {total} case{total === 1 ? '' : 's'}
        </span>
      </div>
      <div className="flex h-2 w-full overflow-hidden rounded-full bg-muted" title={`${agree} agree · ${partial} partial · ${disagree} disagree`}>
        <div className="bg-emerald-500" style={{ width: pct(agree) }} />
        <div className="bg-amber-500" style={{ width: pct(partial) }} />
        <div className="bg-red-500" style={{ width: pct(disagree) }} />
      </div>
    </div>
  );
}

function ConfusionMatrix({ matrix }: { matrix: Record<string, Record<string, number>> }) {
  const max = Math.max(1, ...RECOMMENDATIONS.flatMap((a) => RECOMMENDATIONS.map((h) => matrix[a]?.[h] ?? 0)));
  return (
    <div className="overflow-x-auto">
      <table className="text-xs w-full">
        <thead>
          <tr>
            <th className="text-left text-muted-foreground font-normal p-1">Agent ↓ / Human →</th>
            {RECOMMENDATIONS.map((h) => (
              <th key={h} className="p-1 text-center font-medium">
                {RECOMMENDATION_LABELS[h]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {RECOMMENDATIONS.map((a) => (
            <tr key={a}>
              <td className="p-1 font-medium">{RECOMMENDATION_LABELS[a]}</td>
              {RECOMMENDATIONS.map((h) => {
                const n = matrix[a]?.[h] ?? 0;
                const diagonal = a === h;
                const intensity = n / max;
                return (
                  <td key={h} className="p-1 text-center">
                    <div
                      className={cn(
                        'rounded-md py-2 font-semibold tabular-nums',
                        diagonal ? 'text-emerald-700 dark:text-emerald-300' : 'text-red-700 dark:text-red-300'
                      )}
                      style={{
                        backgroundColor: diagonal
                          ? `rgba(16,185,129,${0.08 + intensity * 0.3})`
                          : `rgba(239,68,68,${0.06 + intensity * 0.3})`,
                      }}
                    >
                      {n}
                    </div>
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

function Trend({ trend }: { trend: TrendPoint[] }) {
  const weeks = Array.from(new Set(trend.map((t) => t.week))).sort();
  const dims = Array.from(new Set(trend.map((t) => t.dimension)));
  if (weeks.length === 0) return <p className="text-xs text-muted-foreground">No weekly data yet.</p>;
  const lookup = new Map(trend.map((t) => [`${t.week}|${t.dimension}`, t.counts]));
  return (
    <div className="overflow-x-auto">
      <table className="text-xs w-full">
        <thead>
          <tr>
            <th className="text-left p-1 text-muted-foreground font-normal">Week</th>
            {dims.map((d) => (
              <th key={d} className="p-1 text-center font-medium">
                {DIMENSION_LABELS[d] ?? d}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((w) => (
            <tr key={w} className="border-t border-border/50">
              <td className="p-1 font-mono">{w}</td>
              {dims.map((d) => {
                const c = lookup.get(`${w}|${d}`);
                return (
                  <td key={d} className="p-1 text-center">
                    {c ? (
                      <span className="inline-flex items-center gap-1">
                        <span className={cn('h-2 w-2 rounded-full', agreementColor(c.agreement))} />
                        {formatAgreement(c.agreement)}
                        <span className="text-muted-foreground">({c.total})</span>
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
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
// Dashboard
// =============================================================================

export function EvaluationDashboard({ onGoToQueue }: { onGoToQueue?: () => void }) {
  const [summary, setSummary] = useState<EvaluationSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchSummary = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/core/evaluations/summary', { credentials: 'include' });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Failed to load metrics');
      }
      setSummary(data as EvaluationSummary);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load metrics');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSummary();
  }, [fetchSummary]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <Card className="p-6">
        <div className="flex items-center gap-2 text-destructive">
          <AlertCircle className="h-5 w-5" />
          <span className="text-sm">{error}</span>
        </div>
        <Button variant="outline" size="sm" className="mt-3" onClick={fetchSummary}>
          Try again
        </Button>
      </Card>
    );
  }

  if (!summary || summary.total_evaluations === 0) {
    return (
      <Card>
        <EmptyState
          icon={<BarChart3 className="h-8 w-8" />}
          title="No evaluations yet"
          description="Agreement, tag distribution and the confusion matrix appear once you have judged some agent decisions. Start in the Review queue."
          action={
            onGoToQueue && (
              <Button size="sm" onClick={onGoToQueue}>
                <ListChecks className="h-4 w-4 mr-1" />
                Open the review queue
              </Button>
            )
          }
        />
      </Card>
    );
  }

  const withData = summary.dimensions.filter((d) => d.counts.total > 0);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {summary.total_evaluations} effective evaluation{summary.total_evaluations === 1 ? '' : 's'} · overall agreement{' '}
          <span className="font-medium text-foreground">{formatAgreement(summary.overall.agreement)}</span>
        </p>
        <Button variant="outline" size="sm" onClick={fetchSummary}>
          <RefreshCw className="h-4 w-4 mr-1" />
          Refresh
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {/* Agreement per dimension */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Agreement per dimension</CardTitle>
            <CardDescription>agree + ½·partial over total effective evaluations</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {withData.map((d) => (
              <AgreementBar key={d.dimension} counts={d.counts} label={DIMENSION_LABELS[d.dimension] ?? d.dimension} />
            ))}
          </CardContent>
        </Card>

        {/* Confusion matrix */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Final verdict confusion matrix</CardTitle>
            <CardDescription>Agent recommendation vs your corrected recommendation</CardDescription>
          </CardHeader>
          <CardContent>
            <ConfusionMatrix matrix={summary.confusion_matrix} />
          </CardContent>
        </Card>

        {/* Per prompt version */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Agreement per prompt version</CardTitle>
            <CardDescription>Which prompt edits helped, per dimension</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {withData.filter((d) => Object.keys(d.by_prompt_version).length > 0).length === 0 && (
              <p className="text-xs text-muted-foreground">No prompt-version data yet.</p>
            )}
            {withData.map((d) =>
              Object.keys(d.by_prompt_version).length ? (
                <div key={d.dimension} className="space-y-2">
                  <div className="text-xs font-medium uppercase text-muted-foreground">
                    {DIMENSION_LABELS[d.dimension] ?? d.dimension}
                  </div>
                  {Object.entries(d.by_prompt_version).map(([v, c]) => (
                    <AgreementBar key={v} counts={c} label={`v${v}`} />
                  ))}
                </div>
              ) : null
            )}
          </CardContent>
        </Card>

        {/* Tag distribution */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Reason tags</CardTitle>
            <CardDescription>What went wrong, per dimension</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {withData.filter((d) => Object.keys(d.tags).length > 0).length === 0 && (
              <p className="text-xs text-muted-foreground">No tags recorded yet.</p>
            )}
            {withData.map((d) =>
              Object.keys(d.tags).length ? (
                <div key={d.dimension}>
                  <div className="text-xs font-medium uppercase text-muted-foreground mb-1">
                    {DIMENSION_LABELS[d.dimension] ?? d.dimension}
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {Object.entries(d.tags).map(([tag, n]) => (
                      <Badge key={tag} variant="secondary" className="font-normal">
                        {REASON_TAG_LABELS[tag as ReasonTag] ?? tag} · {n}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null
            )}
          </CardContent>
        </Card>

        {/* Weekly trend */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Weekly trend</CardTitle>
            <CardDescription>Agreement rate per dimension by ISO week</CardDescription>
          </CardHeader>
          <CardContent>
            <Trend trend={summary.trend} />
          </CardContent>
        </Card>

        {/* Missing information */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">What information was missing</CardTitle>
            <CardDescription>From evaluations tagged &ldquo;Missing context&rdquo;</CardDescription>
          </CardHeader>
          <CardContent>
            {summary.missing_info.length === 0 ? (
              <p className="text-xs text-muted-foreground">Nothing recorded yet.</p>
            ) : (
              <ul className="space-y-1.5">
                {summary.missing_info.map((m) => (
                  <li key={m.text} className="flex items-start justify-between gap-3 text-sm">
                    <span>
                      {m.text}
                      <span className="ml-2 text-[10px] text-muted-foreground">
                        {m.dimensions.map((d) => DIMENSION_LABELS[d] ?? d).join(', ')}
                      </span>
                    </span>
                    <Badge variant="outline" className="shrink-0">×{m.count}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
