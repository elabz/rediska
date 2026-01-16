'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Loader2,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  History,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

interface AnalysisSummary {
  id: number;
  lead_id: number;
  status: string;
  final_recommendation: string | null;
  confidence_score: number | null;
  created_at: string;
  completed_at: string | null;
}

interface AnalysisHistoryProps {
  leadId: number;
  currentAnalysisId?: number;
}

const RECOMMENDATION_ICONS: Record<string, React.ReactNode> = {
  suitable: <CheckCircle className="h-4 w-4 text-emerald-500" />,
  not_recommended: <XCircle className="h-4 w-4 text-red-500" />,
  needs_review: <AlertTriangle className="h-4 w-4 text-amber-500" />,
};

function formatDateTime(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatDuration(startedAt: string, completedAt: string | null): string {
  if (!completedAt) return 'In progress';

  const start = new Date(startedAt);
  const end = new Date(completedAt);
  const durationMs = end.getTime() - start.getTime();
  const seconds = Math.round(durationMs / 1000);

  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds}s`;
}

export function AnalysisHistory({ leadId, currentAnalysisId }: AnalysisHistoryProps) {
  const [history, setHistory] = useState<AnalysisSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`/api/core/leads/${leadId}/analysis/history`, {
        credentials: 'include',
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to fetch history');
      }

      const data = await response.json();
      setHistory(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, [leadId]);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-4">
        <p className="text-sm text-destructive">{error}</p>
      </div>
    );
  }

  if (history.length === 0) {
    return (
      <div className="text-center py-4">
        <History className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
        <p className="text-sm text-muted-foreground">No analysis history yet</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {history.map((analysis) => {
        const isCurrent = analysis.id === currentAnalysisId;
        const isComplete = analysis.status === 'completed';
        const isFailed = analysis.status === 'failed';

        return (
          <div
            key={analysis.id}
            className={cn(
              'flex items-center justify-between p-3 rounded-lg border',
              isCurrent ? 'bg-primary/5 border-primary/30' : 'bg-muted/30'
            )}
          >
            <div className="flex items-center gap-3">
              {/* Status/Recommendation Icon */}
              <div className="shrink-0">
                {isComplete && analysis.final_recommendation ? (
                  RECOMMENDATION_ICONS[analysis.final_recommendation] || (
                    <Clock className="h-4 w-4 text-muted-foreground" />
                  )
                ) : isFailed ? (
                  <XCircle className="h-4 w-4 text-destructive" />
                ) : (
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                )}
              </div>

              {/* Details */}
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">
                    {formatDateTime(analysis.created_at)}
                  </span>
                  {isCurrent && (
                    <Badge variant="secondary" className="text-xs">Current</Badge>
                  )}
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  {analysis.final_recommendation && (
                    <span className="capitalize">
                      {analysis.final_recommendation.replace('_', ' ')}
                    </span>
                  )}
                  {analysis.confidence_score !== null && (
                    <>
                      <span>•</span>
                      <span>{Math.round(analysis.confidence_score * 100)}% confidence</span>
                    </>
                  )}
                  {analysis.completed_at && (
                    <>
                      <span>•</span>
                      <span>{formatDuration(analysis.created_at, analysis.completed_at)}</span>
                    </>
                  )}
                </div>
              </div>
            </div>

            {/* Status Badge */}
            <Badge
              variant="outline"
              className={cn(
                'capitalize text-xs',
                isComplete
                  ? 'bg-emerald-500/10 text-emerald-600 border-emerald-500/30'
                  : isFailed
                    ? 'bg-red-500/10 text-red-600 border-red-500/30'
                    : 'bg-blue-500/10 text-blue-600 border-blue-500/30'
              )}
            >
              {analysis.status}
            </Badge>
          </div>
        );
      })}
    </div>
  );
}
