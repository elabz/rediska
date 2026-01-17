'use client';

import { useState } from 'react';
import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  ThumbsUp,
  ThumbsDown,
  Lightbulb,
  TrendingUp,
  Loader2,
  UserCheck,
  Archive,
  MessageSquare,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface RecommendationCardProps {
  recommendation: string | null;
  reasoning: string | null;
  confidence: number | null;
  metaAnalysis: Record<string, unknown>;
  leadId: number;
  currentStatus: string;
  onStatusChange?: (newStatus: string) => void;
  onInitiateContact?: () => void;
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

// Helper to format field names for display
function formatLabel(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/([A-Z])/g, ' $1')
    .split(' ')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ')
    .trim();
}

// Helper to render any value as React nodes (handles nested objects/arrays)
function renderValue(value: unknown, depth = 0): React.ReactNode {
  if (value === null || value === undefined) return <span className="text-muted-foreground">N/A</span>;
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') {
    // Check if it looks like a percentage (0-1 range)
    if (value >= 0 && value <= 1 && value !== Math.floor(value)) {
      return `${Math.round(value * 100)}%`;
    }
    return value.toString();
  }
  if (typeof value === 'string') {
    if (value === '') return <span className="text-muted-foreground">N/A</span>;
    return value;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-muted-foreground">None</span>;
    // Check if array contains objects
    if (typeof value[0] === 'object' && value[0] !== null) {
      return (
        <div className="space-y-2 mt-1">
          {value.map((item, idx) => (
            <div key={idx} className="text-xs bg-muted/30 p-2 rounded border border-border/50">
              {Object.entries(item as Record<string, unknown>).map(([k, v]) => (
                <div key={k} className="py-0.5">
                  <span className="font-medium text-muted-foreground">{formatLabel(k)}:</span>{' '}
                  <span>{renderValue(v, depth + 1)}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      );
    }
    // Simple array of primitives
    return value.map(String).join(', ');
  }
  if (typeof value === 'object') {
    return (
      <div className={depth > 0 ? "pl-2 border-l border-border/50 ml-1" : "space-y-1 mt-1"}>
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
          <div key={k} className="text-xs py-0.5">
            <span className="font-medium text-muted-foreground">{formatLabel(k)}:</span>{' '}
            <span>{renderValue(v, depth + 1)}</span>
          </div>
        ))}
      </div>
    );
  }
  return String(value);
}

// Fields to skip in the "All Criteria" section (already shown elsewhere)
const SKIP_FIELDS = new Set([
  'recommendation',
  'confidence',
  'priority_level',
  'compatibility_score',
  'strengths',
  'concerns',
  'fail_reasons',
  'suggested_approach',
  'reasoning',
  'non_binary_summaries',
  'dimension_summary',
]);

export function RecommendationCard({
  recommendation,
  reasoning,
  confidence,
  metaAnalysis,
  leadId,
  currentStatus,
  onStatusChange,
  onInitiateContact,
}: RecommendationCardProps) {
  const [updatingStatus, setUpdatingStatus] = useState<string | null>(null);
  const [showAllCriteria, setShowAllCriteria] = useState(true);

  const config = RECOMMENDATION_CONFIG[recommendation || ''] || RECOMMENDATION_CONFIG.needs_review;

  // Extract known fields with fallbacks
  const strengths = (metaAnalysis.strengths as string[]) || [];
  const concerns = (metaAnalysis.concerns as string[])?.length
    ? (metaAnalysis.concerns as string[])
    : ((metaAnalysis.fail_reasons as string[]) || []);
  const compatibilityScore = metaAnalysis.compatibility_score as number | undefined;
  const priorityLevel = metaAnalysis.priority_level as string | undefined;
  const suggestedApproach = metaAnalysis.suggested_approach as string | undefined;
  const dimensionSummary = (metaAnalysis.dimension_summary as Record<string, string>)
    || (metaAnalysis.non_binary_summaries as Record<string, string>)
    || {};

  // Get additional fields not shown elsewhere
  const additionalFields = Object.entries(metaAnalysis).filter(
    ([key]) => !SKIP_FIELDS.has(key)
  );

  const handleStatusUpdate = async (newStatus: string) => {
    setUpdatingStatus(newStatus);
    try {
      const response = await fetch(`/api/core/leads/${leadId}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ status: newStatus }),
      });

      if (!response.ok) {
        throw new Error('Failed to update status');
      }

      onStatusChange?.(newStatus);
    } catch (error) {
      console.error('Failed to update lead status:', error);
    } finally {
      setUpdatingStatus(null);
    }
  };

  const handleContact = async () => {
    await handleStatusUpdate('contact_queued');
    onInitiateContact?.();
  };

  const showActions = currentStatus !== 'contacted' && currentStatus !== 'ignored';

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
        {/* Key Metrics Summary */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="rounded-lg bg-muted/50 p-3 text-center">
            <div className="text-2xl font-bold text-primary">
              {confidence !== null ? `${Math.round(confidence * 100)}%` : 'N/A'}
            </div>
            <div className="text-xs text-muted-foreground">Confidence</div>
          </div>
          <div className="rounded-lg bg-muted/50 p-3 text-center">
            <div className="text-2xl font-bold text-primary">
              {compatibilityScore !== undefined ? `${Math.round(compatibilityScore * 100)}%` : 'N/A'}
            </div>
            <div className="text-xs text-muted-foreground">Compatibility</div>
          </div>
          <div className="rounded-lg bg-muted/50 p-3 text-center">
            <div className="text-2xl font-bold capitalize text-primary">
              {priorityLevel || 'N/A'}
            </div>
            <div className="text-xs text-muted-foreground">Priority</div>
          </div>
          <div className="rounded-lg bg-muted/50 p-3 text-center">
            <div className="text-2xl font-bold uppercase text-primary">
              {(metaAnalysis.suitability as string) || recommendation?.replace('_', ' ') || 'N/A'}
            </div>
            <div className="text-xs text-muted-foreground">Suitability</div>
          </div>
        </div>

        {/* Reasoning */}
        {reasoning && (
          <div className="rounded-lg bg-muted/30 p-3">
            <span className="text-xs font-medium uppercase text-muted-foreground">Reasoning</span>
            <p className="text-sm mt-1 leading-relaxed">{reasoning}</p>
          </div>
        )}

        {/* Strengths and Concerns */}
        <div className="grid gap-4 md:grid-cols-2">
          {strengths.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400">
                <ThumbsUp className="h-4 w-4" />
                <span className="text-sm font-medium">Strengths</span>
              </div>
              <ul className="space-y-1">
                {strengths.map((strength, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-sm text-muted-foreground">
                    <CheckCircle className="h-3 w-3 text-emerald-500 mt-1 shrink-0" />
                    <span>{strength}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {concerns.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400">
                <ThumbsDown className="h-4 w-4" />
                <span className="text-sm font-medium">Concerns / Fail Reasons</span>
              </div>
              <ul className="space-y-1">
                {concerns.map((concern, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-sm text-muted-foreground">
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

        {/* Dimension Summaries (from non_binary_summaries) */}
        {Object.keys(dimensionSummary).length > 0 && (
          <div className="space-y-3">
            <h4 className="text-sm font-medium">Dimension Analysis</h4>
            <div className="grid gap-2">
              {Object.entries(dimensionSummary).map(([dimension, summary]) => (
                <div key={dimension} className="rounded-lg border border-border p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge variant="outline" className="text-xs capitalize">
                      {formatLabel(dimension)}
                    </Badge>
                  </div>
                  <div className="text-sm text-muted-foreground">{renderValue(summary)}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* All Criteria - Collapsible section showing all meta analysis fields */}
        {additionalFields.length > 0 && (
          <div className="border-t border-border pt-4">
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-between p-0 h-auto font-medium"
              onClick={() => setShowAllCriteria(!showAllCriteria)}
            >
              <span className="text-sm">All Analysis Criteria ({additionalFields.length} fields)</span>
              {showAllCriteria ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </Button>

            {showAllCriteria && (
              <div className="mt-3 grid gap-2">
                {additionalFields.map(([key, value]) => (
                  <div key={key} className="py-2 border-b border-border/50 last:border-0">
                    <div className="text-xs font-medium text-muted-foreground mb-1">
                      {formatLabel(key)}:
                    </div>
                    <div className="text-sm">{renderValue(value)}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Action Buttons */}
        {showActions && (
          <div className="border-t border-border pt-4 mt-4">
            <h4 className="text-sm font-medium mb-3">Take Action</h4>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                className="text-emerald-600 border-emerald-300 hover:bg-emerald-50 dark:hover:bg-emerald-950"
                onClick={() => handleStatusUpdate('saved')}
                disabled={updatingStatus !== null || currentStatus === 'saved'}
              >
                {updatingStatus === 'saved' ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <UserCheck className="h-4 w-4 mr-2" />
                )}
                {currentStatus === 'saved' ? 'Kept in Leads' : 'Keep in Leads'}
              </Button>

              <Button
                variant="outline"
                size="sm"
                className="text-red-600 border-red-300 hover:bg-red-50 dark:hover:bg-red-950"
                onClick={() => handleStatusUpdate('ignored')}
                disabled={updatingStatus !== null}
              >
                {updatingStatus === 'ignored' ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Archive className="h-4 w-4 mr-2" />
                )}
                Not a Fit - Archive
              </Button>

              <Button
                size="sm"
                className="bg-blue-600 hover:bg-blue-700 text-white"
                onClick={handleContact}
                disabled={updatingStatus !== null}
              >
                {updatingStatus === 'contact_queued' ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <MessageSquare className="h-4 w-4 mr-2" />
                )}
                Contact
              </Button>
            </div>
          </div>
        )}

        {/* Status indicator if already actioned */}
        {currentStatus === 'ignored' && (
          <div className="border-t border-border pt-4 mt-4">
            <Badge variant="secondary" className="bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300">
              <Archive className="h-3 w-3 mr-1" />
              Archived
            </Badge>
          </div>
        )}
        {currentStatus === 'contacted' && (
          <div className="border-t border-border pt-4 mt-4">
            <Badge variant="secondary" className="bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300">
              <MessageSquare className="h-3 w-3 mr-1" />
              Contacted
            </Badge>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
