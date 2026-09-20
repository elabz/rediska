'use client';

import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, Loader2, RefreshCw, Sparkles } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { DOC_TYPE_LABELS } from '@/lib/similar';

// Mirrors api/routes/ops.py EmbeddingStatusResponse
interface TypeCoverage {
  doc_type: string;
  indexed: number;
  embedded: number;
  coverage: number;
}

interface EmbeddingStatus {
  enabled: boolean;
  configured: boolean;
  model: string | null;
  index: string;
  available: boolean;
  indexed: number;
  embedded: number;
  coverage: number;
  types: TypeCoverage[];
  queue_depth: number | null;
  last_error: string | null;
}

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function CoverageBar({ value }: { value: number }) {
  const width = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
      <div
        className={
          value >= 0.99
            ? 'h-full bg-emerald-500'
            : value >= 0.5
              ? 'h-full bg-amber-500'
              : 'h-full bg-red-500'
        }
        style={{ width: `${width}%` }}
      />
    </div>
  );
}

/**
 * How much of the corpus can be searched by meaning. Counts come straight
 * from Elasticsearch, so the number cannot drift from what search has.
 */
export function EmbeddingCoveragePanel() {
  const [status, setStatus] = useState<EmbeddingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/core/ops/embeddings/status', {
        credentials: 'include',
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof data.detail === 'string' ? data.detail : 'Failed to load embedding coverage',
        );
      }
      setStatus(data as EmbeddingStatus);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load embedding coverage');
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Card data-testid="embedding-coverage-panel">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="h-4 w-4" />
              Semantic coverage
            </CardTitle>
            <CardDescription>
              Documents carrying a vector from the configured model. Search by meaning
              only sees the embedded ones.
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading && !status && (
          <div className="flex items-center justify-center h-24">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}

        {error && !loading && (
          <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            <p>{error}</p>
          </div>
        )}

        {status && (
          <>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge variant={status.enabled ? 'default' : 'secondary'}>
                {status.enabled ? 'hooks on' : 'hooks off'}
              </Badge>
              {!status.configured && (
                <Badge variant="secondary">no embeddings endpoint</Badge>
              )}
              {!status.available && <Badge variant="destructive">index unreachable</Badge>}
              {status.model && (
                <span className="text-muted-foreground">model: {status.model}</span>
              )}
              {status.queue_depth !== null && (
                <span className="text-muted-foreground">
                  queue: {status.queue_depth}
                </span>
              )}
            </div>

            <div>
              <div className="flex items-baseline justify-between text-sm">
                <span className="font-medium">All types</span>
                <span className="tabular-nums">
                  {status.embedded.toLocaleString()} / {status.indexed.toLocaleString()} ·{' '}
                  {pct(status.coverage)}
                </span>
              </div>
              <div className="mt-1">
                <CoverageBar value={status.coverage} />
              </div>
            </div>

            <div className="space-y-2">
              {status.types.map((row) => (
                <div key={row.doc_type} data-testid="coverage-row">
                  <div className="flex items-baseline justify-between text-xs">
                    <span>{DOC_TYPE_LABELS[row.doc_type] ?? row.doc_type}</span>
                    <span className="tabular-nums text-muted-foreground">
                      {row.embedded.toLocaleString()} / {row.indexed.toLocaleString()} ·{' '}
                      {pct(row.coverage)}
                    </span>
                  </div>
                  <div className="mt-1">
                    <CoverageBar value={row.coverage} />
                  </div>
                </div>
              ))}
              {status.types.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  Nothing indexed yet.
                </p>
              )}
            </div>

            {status.last_error && (
              <p className="text-xs text-muted-foreground">Last error: {status.last_error}</p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
