'use client';

import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, Gauge, Loader2, Play, RefreshCw } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

// Mirrors domain/services/calibration_report.py payload
interface Rate {
  total: number;
  failed: number;
  rate: number | null;
}

interface LeadMetrics {
  leads_created: number;
  suitable_leads: number;
  suitable_ignored: number;
  suitable_ignored_rate: number | null;
  suitable_contacted: number;
  suitable_contacted_rate: number | null;
  contacted: number;
  contacted_engaged: number;
  contacted_engaged_rate: number | null;
  expired: number;
  untouched: number;
  by_priority: Record<string, number>;
}

interface PostMetrics {
  posts_analyzed: number;
  recommendations: Record<string, number>;
  needs_review: { total: number; promoted: number; dismissed: number; pending: number };
  gate_outcomes: Record<string, { fail: number; unclear: number }>;
  posts_without_gate_verdict: number;
  dimension_failures: Record<string, Rate>;
}

interface ReportPayload {
  period_start: string;
  period_end: string;
  lead_cohort_start: string;
  generated_at: string;
  gate_outcomes_best_effort: boolean;
  overall: {
    leads: LeadMetrics;
    manual_leads: LeadMetrics;
    posts: PostMetrics;
    needs_review_queue_size: number;
    dimension_failures: Record<string, Rate>;
  };
  watches: {
    watch_id: number;
    source_location: string | null;
    search_query: string | null;
    min_confidence: number | null;
    leads: LeadMetrics;
    posts: PostMetrics;
  }[];
}

interface StoredReport {
  id: number;
  period_start: string;
  period_end: string;
  created_at: string;
  report: ReportPayload;
}

function pct(rate: number | null | undefined): string {
  return rate === null || rate === undefined ? '—' : `${Math.round(rate * 100)}%`;
}

function day(dateString: string): string {
  return new Date(dateString).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

function Stat({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-xl font-semibold tabular-nums">{value}</div>
      {detail && <div className="text-xs text-muted-foreground mt-0.5">{detail}</div>}
    </div>
  );
}

export function CalibrationReportPanel() {
  const [reports, setReports] = useState<StoredReport[]>([]);
  const [selectedId, setSelectedId] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/core/ops/calibration-reports?limit=12', {
        credentials: 'include',
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Failed to load reports');
      }
      const list = data.reports as StoredReport[];
      setReports(list);
      setSelectedId((prev) =>
        prev && list.some((r) => String(r.id) === prev) ? prev : list[0] ? String(list[0].id) : ''
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load reports');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const generate = async () => {
    setGenerating(true);
    setNotice(null);
    try {
      const response = await fetch('/api/core/ops/calibration-reports/generate', {
        method: 'POST',
        credentials: 'include',
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Failed to queue report');
      }
      setNotice(`${data.message} Refresh in a moment to see it.`);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : 'Failed to queue report');
    } finally {
      setGenerating(false);
    }
  };

  const selected = reports.find((r) => String(r.id) === selectedId) ?? null;
  const report = selected?.report;

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-teal-500/10">
              <Gauge className="h-5 w-5 text-teal-500" />
            </div>
            <div>
              <CardTitle className="text-lg">Calibration report</CardTitle>
              <CardDescription>
                How analysis verdicts compare with what you actually did (weekly)
              </CardDescription>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {reports.length > 1 && (
              <Select value={selectedId} onValueChange={setSelectedId}>
                <SelectTrigger className="h-8 w-44">
                  <SelectValue placeholder="Select report" />
                </SelectTrigger>
                <SelectContent>
                  {reports.map((r) => (
                    <SelectItem key={r.id} value={String(r.id)}>
                      Week ending {day(r.period_end)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <Button variant="outline" size="sm" onClick={generate} disabled={generating}>
              {generating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <>
                  <Play className="h-4 w-4 mr-1" />
                  Generate now
                </>
              )}
            </Button>
            <Button variant="ghost" size="sm" onClick={load} disabled={loading}>
              <RefreshCw className={loading ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-5">
        {notice && <p className="text-sm text-muted-foreground">{notice}</p>}

        {loading && reports.length === 0 ? (
          <div className="flex items-center justify-center h-24">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : error ? (
          <div className="flex items-center justify-between gap-2 rounded-lg border border-destructive/50 bg-destructive/10 p-3">
            <span className="text-sm text-destructive flex items-center gap-2">
              <AlertCircle className="h-4 w-4" /> {error}
            </span>
            <Button variant="outline" size="sm" onClick={load}>
              Try again
            </Button>
          </div>
        ) : !report ? (
          <p className="text-sm text-muted-foreground">
            No calibration report yet. One is generated every Monday at 06:00 UTC, or use
            Generate now.
          </p>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              Scout posts and dimensions: {day(report.period_start)} – {day(report.period_end)}.
              Lead verdicts: leads created since {day(report.lead_cohort_start)}.
            </p>

            <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
              <Stat
                label="Suitable → ignored"
                value={pct(report.overall.leads.suitable_ignored_rate)}
                detail={`${report.overall.leads.suitable_ignored} of ${report.overall.leads.suitable_leads} suitable`}
              />
              <Stat
                label="Suitable → contacted"
                value={pct(report.overall.leads.suitable_contacted_rate)}
                detail={`${report.overall.leads.suitable_contacted} of ${report.overall.leads.suitable_leads} suitable`}
              />
              <Stat
                label="Contacted → engaged"
                value={pct(report.overall.leads.contacted_engaged_rate)}
                detail={`${report.overall.leads.contacted_engaged} of ${report.overall.leads.contacted} contacted`}
              />
              <Stat
                label="Needs-review queue"
                value={String(report.overall.needs_review_queue_size)}
                detail={`${report.overall.posts.needs_review.promoted} promoted · ${report.overall.posts.needs_review.dismissed} dismissed this week`}
              />
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">Watch</th>
                    <th className="py-2 pr-3 font-medium text-right">Analysed</th>
                    <th className="py-2 pr-3 font-medium text-right">Suit / Rev / Not</th>
                    <th className="py-2 pr-3 font-medium text-right">Review: promo / dism / pend</th>
                    <th className="py-2 pr-3 font-medium text-right">Suitable leads</th>
                    <th className="py-2 pr-3 font-medium text-right">→ ignored</th>
                    <th className="py-2 font-medium text-right">→ contacted</th>
                  </tr>
                </thead>
                <tbody>
                  {report.watches.length === 0 && (
                    <tr>
                      <td colSpan={7} className="py-3 text-muted-foreground">
                        No watch activity in this period.
                      </td>
                    </tr>
                  )}
                  {report.watches.map((w) => (
                    <tr key={w.watch_id} className="border-b last:border-0">
                      <td className="py-2 pr-3">
                        <div className="font-medium">
                          {w.source_location ? `r/${w.source_location}` : `Watch #${w.watch_id}`}
                        </div>
                        {w.search_query && (
                          <div className="text-xs text-muted-foreground truncate max-w-48">
                            “{w.search_query}”
                          </div>
                        )}
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">{w.posts.posts_analyzed}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">
                        {w.posts.recommendations.suitable ?? 0} / {w.posts.recommendations.needs_review ?? 0} /{' '}
                        {w.posts.recommendations.not_recommended ?? 0}
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">
                        {w.posts.needs_review.promoted} / {w.posts.needs_review.dismissed} /{' '}
                        {w.posts.needs_review.pending}
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">{w.leads.suitable_leads}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{pct(w.leads.suitable_ignored_rate)}</td>
                      <td className="py-2 text-right tabular-nums">{pct(w.leads.suitable_contacted_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <h4 className="text-sm font-medium mb-2 flex items-center gap-2">
                  Gate outcomes
                  {report.gate_outcomes_best_effort && (
                    <Badge variant="outline" className="text-[10px]">best-effort</Badge>
                  )}
                </h4>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-xs text-muted-foreground">
                      <th className="py-1.5 pr-3 font-medium">Gate</th>
                      <th className="py-1.5 pr-3 font-medium text-right">Fail</th>
                      <th className="py-1.5 font-medium text-right">Unclear</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(report.overall.posts.gate_outcomes).map(([gate, counts]) => (
                      <tr key={gate} className="border-b last:border-0">
                        <td className="py-1.5 pr-3">{gate.replace('_', ' ')}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{counts.fail}</td>
                        <td className="py-1.5 text-right tabular-nums">{counts.unclear}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {report.overall.posts.posts_without_gate_verdict > 0 && (
                  <p className="text-xs text-muted-foreground mt-1">
                    {report.overall.posts.posts_without_gate_verdict} analysed post(s) carry no
                    structured gate verdict.
                  </p>
                )}
              </div>

              <div>
                <h4 className="text-sm font-medium mb-2">Dimension failure rates</h4>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-xs text-muted-foreground">
                      <th className="py-1.5 pr-3 font-medium">Dimension</th>
                      <th className="py-1.5 pr-3 font-medium text-right">Attempts failed</th>
                      <th className="py-1.5 font-medium text-right">Missing on posts</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(report.overall.posts.dimension_failures).map(([dim, posts]) => {
                      const attempts = report.overall.dimension_failures[dim];
                      return (
                        <tr key={dim} className="border-b last:border-0">
                          <td className="py-1.5 pr-3">{dim.replace('_', ' ')}</td>
                          <td className="py-1.5 pr-3 text-right tabular-nums">
                            {attempts ? `${pct(attempts.rate)} (${attempts.failed}/${attempts.total})` : '—'}
                          </td>
                          <td className="py-1.5 text-right tabular-nums">
                            {pct(posts.rate)} ({posts.failed}/{posts.total})
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
