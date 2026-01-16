'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Loader2,
  RefreshCw,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

import { DimensionCard } from './DimensionCard';
import { RecommendationCard } from './RecommendationCard';
import { AnalysisHistory } from './AnalysisHistory';

// Types matching backend schemas
interface DimensionAnalysisResult {
  dimension: string;
  status: string;
  output: Record<string, unknown> | null;
  error: string | null;
  model_info: Record<string, unknown> | null;
  started_at: string;
  completed_at: string | null;
}

interface MultiAgentAnalysis {
  id: number;
  lead_id: number;
  account_id: number;
  status: string;
  started_at: string;
  completed_at: string | null;
  demographics: DimensionAnalysisResult | null;
  preferences: DimensionAnalysisResult | null;
  relationship_goals: DimensionAnalysisResult | null;
  risk_flags: DimensionAnalysisResult | null;
  sexual_preferences: DimensionAnalysisResult | null;
  final_recommendation: string | null;
  recommendation_reasoning: string | null;
  confidence_score: number | null;
  meta_analysis: Record<string, unknown> | null;
  prompt_versions: Record<string, number>;
  model_info: Record<string, unknown> | null;
}

interface LeadAnalysisPanelProps {
  leadId: number;
  hasAnalysis: boolean;
  currentRecommendation: string | null;
  currentConfidence: number | null;
  onAnalysisComplete?: () => void;
}

const RECOMMENDATION_STYLES: Record<string, { bg: string; text: string; icon: React.ReactNode }> = {
  suitable: {
    bg: 'bg-emerald-500/10 border-emerald-500/30',
    text: 'text-emerald-600 dark:text-emerald-400',
    icon: <CheckCircle className="h-5 w-5" />,
  },
  not_recommended: {
    bg: 'bg-red-500/10 border-red-500/30',
    text: 'text-red-600 dark:text-red-400',
    icon: <XCircle className="h-5 w-5" />,
  },
  needs_review: {
    bg: 'bg-amber-500/10 border-amber-500/30',
    text: 'text-amber-600 dark:text-amber-400',
    icon: <AlertTriangle className="h-5 w-5" />,
  },
};

export function LeadAnalysisPanel({
  leadId,
  hasAnalysis,
  currentRecommendation,
  currentConfidence,
  onAnalysisComplete,
}: LeadAnalysisPanelProps) {
  const [analysis, setAnalysis] = useState<MultiAgentAnalysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const fetchAnalysis = useCallback(async () => {
    if (!hasAnalysis) return;

    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`/api/core/leads/${leadId}/analysis`, {
        credentials: 'include',
      });

      if (response.status === 404) {
        // No analysis yet
        setAnalysis(null);
        return;
      }

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to fetch analysis');
      }

      const data = await response.json();
      setAnalysis(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, [leadId, hasAnalysis]);

  useEffect(() => {
    fetchAnalysis();
  }, [fetchAnalysis]);

  const runAnalysis = async () => {
    setAnalyzing(true);
    setError(null);

    try {
      const response = await fetch(`/api/core/leads/${leadId}/analyze-multi`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to run analysis');
      }

      const data = await response.json();
      setAnalysis(data);
      onAnalysisComplete?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed');
    } finally {
      setAnalyzing(false);
    }
  };

  // Loading state
  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // No analysis yet
  if (!analysis && !hasAnalysis) {
    return (
      <div className="text-center py-8">
        <div className="flex items-center justify-center w-16 h-16 rounded-full bg-muted mx-auto mb-4">
          <Clock className="h-8 w-8 text-muted-foreground" />
        </div>
        <h3 className="font-medium mb-2">No Analysis Yet</h3>
        <p className="text-sm text-muted-foreground mb-4">
          Run multi-agent analysis to get AI-powered insights about this lead.
        </p>
        <Button onClick={runAnalysis} disabled={analyzing}>
          {analyzing ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              Analyzing...
            </>
          ) : (
            <>
              <RefreshCw className="h-4 w-4 mr-2" />
              Run Multi-Agent Analysis
            </>
          )}
        </Button>
        {error && (
          <p className="text-sm text-destructive mt-4">{error}</p>
        )}
      </div>
    );
  }

  // Analysis in progress
  if (analysis?.status === 'running' || analysis?.status === 'pending') {
    return (
      <div className="text-center py-8">
        <Loader2 className="h-12 w-12 animate-spin text-purple-500 mx-auto mb-4" />
        <h3 className="font-medium mb-2">Analysis in Progress</h3>
        <p className="text-sm text-muted-foreground">
          The AI agents are analyzing this lead. This may take a minute...
        </p>
        <Button
          variant="outline"
          size="sm"
          className="mt-4"
          onClick={fetchAnalysis}
        >
          <RefreshCw className="h-4 w-4 mr-2" />
          Refresh Status
        </Button>
      </div>
    );
  }

  // Analysis failed
  if (analysis?.status === 'failed') {
    return (
      <div className="text-center py-8">
        <XCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
        <h3 className="font-medium mb-2">Analysis Failed</h3>
        <p className="text-sm text-muted-foreground mb-4">
          The analysis could not be completed. Please try again.
        </p>
        <Button onClick={runAnalysis} disabled={analyzing}>
          {analyzing ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              Retrying...
            </>
          ) : (
            <>
              <RefreshCw className="h-4 w-4 mr-2" />
              Retry Analysis
            </>
          )}
        </Button>
      </div>
    );
  }

  // Analysis complete - show results
  const recommendation = analysis?.final_recommendation || currentRecommendation;
  const confidence = analysis?.confidence_score ?? currentConfidence;
  const recStyle = RECOMMENDATION_STYLES[recommendation || ''] || RECOMMENDATION_STYLES.needs_review;

  return (
    <div className="space-y-6">
      {/* Status Bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {recommendation && (
            <div className={cn(
              'flex items-center gap-2 px-3 py-1.5 rounded-lg border',
              recStyle.bg
            )}>
              <span className={recStyle.text}>{recStyle.icon}</span>
              <span className={cn('font-medium capitalize', recStyle.text)}>
                {recommendation.replace('_', ' ')}
              </span>
            </div>
          )}
          {confidence !== null && (
            <Badge variant="secondary">
              {Math.round(confidence * 100)}% confidence
            </Badge>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={runAnalysis}
          disabled={analyzing}
        >
          {analyzing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <>
              <RefreshCw className="h-4 w-4 mr-1" />
              Re-analyze
            </>
          )}
        </Button>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive bg-destructive/10 p-3">
          <p className="text-sm text-destructive">{error}</p>
        </div>
      )}

      {/* Recommendation Card */}
      {analysis?.meta_analysis && (
        <RecommendationCard
          recommendation={analysis.final_recommendation}
          reasoning={analysis.recommendation_reasoning}
          confidence={analysis.confidence_score}
          metaAnalysis={analysis.meta_analysis}
        />
      )}

      {/* Dimension Cards */}
      <div className="grid gap-4 md:grid-cols-2">
        {analysis?.demographics && (
          <DimensionCard
            dimension="demographics"
            result={analysis.demographics}
          />
        )}
        {analysis?.preferences && (
          <DimensionCard
            dimension="preferences"
            result={analysis.preferences}
          />
        )}
        {analysis?.relationship_goals && (
          <DimensionCard
            dimension="relationship_goals"
            result={analysis.relationship_goals}
          />
        )}
        {analysis?.risk_flags && (
          <DimensionCard
            dimension="risk_flags"
            result={analysis.risk_flags}
          />
        )}
        {analysis?.sexual_preferences && (
          <DimensionCard
            dimension="sexual_preferences"
            result={analysis.sexual_preferences}
          />
        )}
      </div>

      {/* Analysis History Toggle */}
      <div className="border-t border-border pt-4">
        <Button
          variant="ghost"
          className="w-full justify-between"
          onClick={() => setShowHistory(!showHistory)}
        >
          <span className="text-sm">Analysis History</span>
          {showHistory ? (
            <ChevronUp className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
        </Button>
        {showHistory && (
          <div className="mt-4">
            <AnalysisHistory leadId={leadId} currentAnalysisId={analysis?.id} />
          </div>
        )}
      </div>
    </div>
  );
}
