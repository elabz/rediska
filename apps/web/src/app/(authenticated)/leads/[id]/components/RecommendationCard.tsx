'use client';

import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  ThumbsUp,
  ThumbsDown,
  Lightbulb,
  TrendingUp,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

interface MetaAnalysis {
  strengths?: string[];
  concerns?: string[];
  compatibility_score?: number;
  priority_level?: string;
  suggested_approach?: string;
  dimension_summary?: Record<string, string>;
}

interface RecommendationCardProps {
  recommendation: string | null;
  reasoning: string | null;
  confidence: number | null;
  metaAnalysis: Record<string, unknown>;
}

const RECOMMENDATION_CONFIG: Record<string, {
  icon: React.ReactNode;
  title: string;
  bgColor: string;
  textColor: string;
  borderColor: string;
}> = {
  suitable: {
    icon: <CheckCircle className="h-6 w-6" />,
    title: 'Suitable Match',
    bgColor: 'bg-emerald-500/10',
    textColor: 'text-emerald-600 dark:text-emerald-400',
    borderColor: 'border-emerald-500/30',
  },
  not_recommended: {
    icon: <XCircle className="h-6 w-6" />,
    title: 'Not Recommended',
    bgColor: 'bg-red-500/10',
    textColor: 'text-red-600 dark:text-red-400',
    borderColor: 'border-red-500/30',
  },
  needs_review: {
    icon: <AlertTriangle className="h-6 w-6" />,
    title: 'Needs Review',
    bgColor: 'bg-amber-500/10',
    textColor: 'text-amber-600 dark:text-amber-400',
    borderColor: 'border-amber-500/30',
  },
};

const PRIORITY_COLORS: Record<string, string> = {
  high: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/30',
  medium: 'bg-blue-500/10 text-blue-600 border-blue-500/30',
  low: 'bg-muted text-muted-foreground',
};

export function RecommendationCard({
  recommendation,
  reasoning,
  confidence,
  metaAnalysis,
}: RecommendationCardProps) {
  const config = RECOMMENDATION_CONFIG[recommendation || ''] || RECOMMENDATION_CONFIG.needs_review;
  const meta = metaAnalysis as MetaAnalysis;

  const strengths = meta.strengths || [];
  const concerns = meta.concerns || [];
  const compatibilityScore = meta.compatibility_score;
  const priorityLevel = meta.priority_level;
  const suggestedApproach = meta.suggested_approach;

  return (
    <Card className={cn('border-2', config.borderColor)}>
      <CardHeader className={cn('pb-3', config.bgColor)}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className={config.textColor}>{config.icon}</span>
            <div>
              <CardTitle className={cn('text-lg', config.textColor)}>
                {config.title}
              </CardTitle>
              {confidence !== null && (
                <p className="text-sm text-muted-foreground">
                  {Math.round(confidence * 100)}% confidence
                </p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {priorityLevel && (
              <Badge
                variant="outline"
                className={cn('capitalize', PRIORITY_COLORS[priorityLevel])}
              >
                {priorityLevel} priority
              </Badge>
            )}
            {compatibilityScore !== undefined && (
              <Badge variant="secondary">
                <TrendingUp className="h-3 w-3 mr-1" />
                {Math.round(compatibilityScore * 100)}% compatible
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent className="pt-4 space-y-4">
        {/* Reasoning */}
        {reasoning && (
          <div>
            <p className="text-sm leading-relaxed">{reasoning}</p>
          </div>
        )}

        {/* Strengths and Concerns */}
        <div className="grid gap-4 md:grid-cols-2">
          {/* Strengths */}
          {strengths.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400">
                <ThumbsUp className="h-4 w-4" />
                <span className="text-sm font-medium">Strengths</span>
              </div>
              <ul className="space-y-1">
                {strengths.map((strength, idx) => (
                  <li
                    key={idx}
                    className="flex items-start gap-2 text-sm text-muted-foreground"
                  >
                    <CheckCircle className="h-3 w-3 text-emerald-500 mt-1 shrink-0" />
                    <span>{strength}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Concerns */}
          {concerns.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400">
                <ThumbsDown className="h-4 w-4" />
                <span className="text-sm font-medium">Concerns</span>
              </div>
              <ul className="space-y-1">
                {concerns.map((concern, idx) => (
                  <li
                    key={idx}
                    className="flex items-start gap-2 text-sm text-muted-foreground"
                  >
                    <AlertTriangle className="h-3 w-3 text-amber-500 mt-1 shrink-0" />
                    <span>{concern}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Suggested Approach */}
        {suggestedApproach && (
          <div className="rounded-lg bg-muted/50 p-3">
            <div className="flex items-center gap-2 mb-2">
              <Lightbulb className="h-4 w-4 text-amber-500" />
              <span className="text-sm font-medium">Suggested Approach</span>
            </div>
            <p className="text-sm text-muted-foreground">{suggestedApproach}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
