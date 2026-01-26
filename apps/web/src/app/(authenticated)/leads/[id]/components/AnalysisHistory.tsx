'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Loader2,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  History,
  ChevronDown,
  ChevronUp,
  User,
  Heart,
  Target,
  Flame,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';

interface AnalysisSummary {
  id: number;
  lead_id: number;
  status: string;
  final_recommendation: string | null;
  confidence_score: number | null;
  created_at: string;
  completed_at: string | null;
}

interface DimensionResult {
  dimension: string;
  status: string;
  output: Record<string, unknown> | null;
  error: string | null;
}

interface FullAnalysis {
  id: number;
  lead_id: number;
  status: string;
  started_at: string;
  completed_at: string | null;
  demographics: DimensionResult | null;
  preferences: DimensionResult | null;
  relationship_goals: DimensionResult | null;
  risk_flags: DimensionResult | null;
  sexual_preferences: DimensionResult | null;
  final_recommendation: string | null;
  recommendation_reasoning: string | null;
  confidence_score: number | null;
  meta_analysis: Record<string, unknown> | null;
}

interface AnalysisHistoryProps {
  leadId: number;
  currentAnalysisId?: number;
}

const DIMENSION_CONFIG: Record<string, { title: string; icon: React.ReactNode; color: string }> = {
  demographics: { title: 'Demographics', icon: <User className="h-3 w-3" />, color: 'text-blue-500' },
  preferences: { title: 'Preferences', icon: <Heart className="h-3 w-3" />, color: 'text-pink-500' },
  relationship_goals: { title: 'Relationship Goals', icon: <Target className="h-3 w-3" />, color: 'text-purple-500' },
  risk_flags: { title: 'Risk Flags', icon: <AlertTriangle className="h-3 w-3" />, color: 'text-amber-500' },
  sexual_preferences: { title: 'Intimacy', icon: <Flame className="h-3 w-3" />, color: 'text-red-500' },
};

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
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [fullAnalyses, setFullAnalyses] = useState<Record<number, FullAnalysis>>({});
  const [loadingAnalysisId, setLoadingAnalysisId] = useState<number | null>(null);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`/api/core/leads/${leadId}/analysis/history`, {
        credentials: 'include',
      });

      if (!response.ok) {
        const data = await response.json();
        let errorMessage = 'Failed to fetch history';
        if (typeof data.detail === 'string') {
          errorMessage = data.detail;
        } else if (Array.isArray(data.detail)) {
          errorMessage = data.detail.map((e: { msg?: string }) => e.msg || 'Error').join(', ');
        }
        throw new Error(errorMessage);
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

  const fetchFullAnalysis = async (analysisId: number) => {
    if (fullAnalyses[analysisId]) {
      setExpandedId(expandedId === analysisId ? null : analysisId);
      return;
    }

    setLoadingAnalysisId(analysisId);
    try {
      const response = await fetch(`/api/core/leads/${leadId}/analysis/${analysisId}`, {
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error('Failed to fetch analysis details');
      }

      const data = await response.json();
      setFullAnalyses(prev => ({ ...prev, [analysisId]: data }));
      setExpandedId(analysisId);
    } catch (err) {
      console.error('Failed to fetch analysis:', err);
    } finally {
      setLoadingAnalysisId(null);
    }
  };

  const renderValue = (value: unknown, depth: number = 0): React.ReactNode => {
    if (value === null || value === undefined) {
      return <span className="text-muted-foreground">-</span>;
    }
    if (typeof value === 'boolean') {
      return <span className={value ? 'text-emerald-600' : 'text-red-500'}>{value ? 'Yes' : 'No'}</span>;
    }
    if (typeof value === 'number') {
      // Format percentages nicely
      if (value >= 0 && value <= 1) {
        return `${Math.round(value * 100)}%`;
      }
      return value.toString();
    }
    if (Array.isArray(value)) {
      if (value.length === 0) {
        return <span className="text-muted-foreground">None</span>;
      }
      // Check if any items are objects/arrays (not just the first)
      const hasComplexItems = value.some(item => typeof item === 'object' && item !== null);
      if (hasComplexItems) {
        return (
          <ul className="list-disc list-inside space-y-1">
            {value.map((item, i) => (
              <li key={i}>{renderValue(item, depth + 1)}</li>
            ))}
          </ul>
        );
      }
      // All items are primitives - safely join as strings
      return value.map(item => String(item)).join(', ');
    }
    if (typeof value === 'object') {
      // Render nested object as key-value pairs
      const entries = Object.entries(value as Record<string, unknown>);
      if (entries.length === 0) {
        return <span className="text-muted-foreground">-</span>;
      }
      return (
        <div className={cn("space-y-1", depth > 0 && "pl-2 border-l border-muted")}>
          {entries.map(([k, v]) => (
            <div key={k} className="flex items-start gap-2">
              <span className="text-muted-foreground capitalize shrink-0">
                {k.replace(/_/g, ' ')}:
              </span>
              <span className="flex-1">{renderValue(v, depth + 1)}</span>
            </div>
          ))}
        </div>
      );
    }
    return String(value);
  };

  const renderDimensionOutput = (output: Record<string, unknown>) => {
    const skipFields = ['evidence', 'model_config'];
    const entries = Object.entries(output).filter(([key]) => !skipFields.includes(key));

    return (
      <div className="space-y-2">
        {entries.map(([key, value]) => (
          <div key={key} className="text-xs">
            <div className="flex items-start gap-2">
              <span className="text-muted-foreground min-w-[110px] capitalize font-medium shrink-0">
                {key.replace(/_/g, ' ')}:
              </span>
              <span className="flex-1">{renderValue(value)}</span>
            </div>
          </div>
        ))}
      </div>
    );
  };

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
        const isExpanded = expandedId === analysis.id;
        const fullAnalysis = fullAnalyses[analysis.id];

        return (
          <Collapsible
            key={analysis.id}
            open={isExpanded}
            onOpenChange={() => fetchFullAnalysis(analysis.id)}
          >
            <CollapsibleTrigger asChild>
              <div
                className={cn(
                  'flex items-center justify-between p-3 rounded-lg border cursor-pointer hover:bg-muted/50 transition-colors',
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

                <div className="flex items-center gap-2">
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
                  {loadingAnalysisId === analysis.id ? (
                    <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                  ) : isExpanded ? (
                    <ChevronUp className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <ChevronDown className="h-4 w-4 text-muted-foreground" />
                  )}
                </div>
              </div>
            </CollapsibleTrigger>

            <CollapsibleContent>
              {fullAnalysis && (
                <div className="mt-2 p-4 border rounded-lg bg-background space-y-4">
                  {/* Meta Analysis / Reasoning */}
                  {fullAnalysis.meta_analysis && (
                    <div className="p-3 rounded-lg bg-muted/50 border">
                      <h4 className="text-sm font-medium mb-2 flex items-center gap-2">
                        <CheckCircle className="h-4 w-4 text-purple-500" />
                        Meta-Analysis Decision
                      </h4>
                      {fullAnalysis.recommendation_reasoning && (
                        <div className="text-sm mb-3 whitespace-pre-wrap">
                          {typeof fullAnalysis.recommendation_reasoning === 'string'
                            ? fullAnalysis.recommendation_reasoning
                            : renderValue(fullAnalysis.recommendation_reasoning)}
                        </div>
                      )}
                      {renderDimensionOutput(fullAnalysis.meta_analysis)}
                    </div>
                  )}

                  {/* Agent Outputs Grid */}
                  <div className="grid gap-3 md:grid-cols-2">
                    {Object.entries(DIMENSION_CONFIG).map(([key, config]) => {
                      const dimResult = fullAnalysis[key as keyof FullAnalysis] as DimensionResult | null;
                      if (!dimResult?.output) return null;

                      return (
                        <div key={key} className="p-3 rounded-lg border bg-muted/30">
                          <h5 className={`text-xs font-medium mb-2 flex items-center gap-1.5 ${config.color}`}>
                            {config.icon}
                            {config.title}
                          </h5>
                          {renderDimensionOutput(dimResult.output)}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </CollapsibleContent>
          </Collapsible>
        );
      })}
    </div>
  );
}
