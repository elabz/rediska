'use client';

import { useState } from 'react';
import {
  User,
  Heart,
  Target,
  AlertTriangle,
  Flame,
  ChevronDown,
  ChevronUp,
  CheckCircle,
  XCircle,
  MapPin,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface DimensionAnalysisResult {
  dimension: string;
  status: string;
  output: Record<string, unknown> | null;
  error: string | null;
  model_info: Record<string, unknown> | null;
  started_at: string;
  completed_at: string | null;
}

interface DimensionCardProps {
  dimension: string;
  result: DimensionAnalysisResult;
}

const DIMENSION_CONFIG: Record<string, {
  title: string;
  icon: React.ReactNode;
  color: string;
  bgColor: string;
}> = {
  demographics: {
    title: 'Demographics',
    icon: <User className="h-4 w-4" />,
    color: 'text-blue-500',
    bgColor: 'bg-blue-500/10',
  },
  preferences: {
    title: 'Preferences & Interests',
    icon: <Heart className="h-4 w-4" />,
    color: 'text-pink-500',
    bgColor: 'bg-pink-500/10',
  },
  relationship_goals: {
    title: 'Relationship Goals',
    icon: <Target className="h-4 w-4" />,
    color: 'text-purple-500',
    bgColor: 'bg-purple-500/10',
  },
  risk_flags: {
    title: 'Risk Assessment',
    icon: <AlertTriangle className="h-4 w-4" />,
    color: 'text-amber-500',
    bgColor: 'bg-amber-500/10',
  },
  sexual_preferences: {
    title: 'Intimacy & Compatibility',
    icon: <Flame className="h-4 w-4" />,
    color: 'text-red-500',
    bgColor: 'bg-red-500/10',
  },
};

function ConfidenceMeter({ value, label }: { value: number; label?: string }) {
  const percentage = Math.round(value * 100);
  return (
    <div className="flex items-center gap-2">
      {label && <span className="text-xs text-muted-foreground">{label}:</span>}
      <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden max-w-[60px]">
        <div
          className={cn(
            'h-full rounded-full transition-all',
            percentage >= 70 ? 'bg-emerald-500' :
            percentage >= 40 ? 'bg-amber-500' : 'bg-red-500'
          )}
          style={{ width: `${percentage}%` }}
        />
      </div>
      <span className="text-xs font-medium">{percentage}%</span>
    </div>
  );
}

function TagList({ items, color = 'default' }: { items: string[]; color?: 'default' | 'success' | 'warning' | 'danger' }) {
  if (!items?.length) return null;

  const colorClasses = {
    default: 'bg-muted text-muted-foreground',
    success: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20',
    warning: 'bg-amber-500/10 text-amber-600 border-amber-500/20',
    danger: 'bg-red-500/10 text-red-600 border-red-500/20',
  };

  return (
    <div className="flex flex-wrap gap-1">
      {items.map((item, idx) => (
        <Badge key={idx} variant="outline" className={cn('text-xs', colorClasses[color])}>
          {item}
        </Badge>
      ))}
    </div>
  );
}

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

// Helper to render any value
function renderValue(value: unknown): React.ReactNode {
  if (value === null || value === undefined) return <span className="text-muted-foreground">N/A</span>;
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') {
    // Check if it looks like a confidence score (0-1 range)
    if (value >= 0 && value <= 1 && value !== Math.floor(value)) {
      return <ConfidenceMeter value={value} />;
    }
    return value.toString();
  }
  if (typeof value === 'string') {
    if (value === '') return <span className="text-muted-foreground">N/A</span>;
    return value;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-muted-foreground">None</span>;
    // Check if it's an array of objects
    if (typeof value[0] === 'object' && value[0] !== null) {
      return (
        <div className="space-y-2 mt-1">
          {value.map((item, idx) => (
            <div key={idx} className="text-xs bg-muted/30 p-2 rounded">
              {Object.entries(item as Record<string, unknown>).map(([k, v]) => (
                <div key={k}>
                  <span className="font-medium">{formatLabel(k)}:</span>{' '}
                  <span className="text-muted-foreground">{String(v)}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      );
    }
    // Simple array - render as tags
    return <TagList items={value.map(String)} />;
  }
  if (typeof value === 'object') {
    return (
      <div className="space-y-1 mt-1">
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
          <div key={k} className="text-xs">
            <span className="font-medium">{formatLabel(k)}:</span>{' '}
            <span className="text-muted-foreground">{String(v)}</span>
          </div>
        ))}
      </div>
    );
  }
  return String(value);
}

// Generic renderer that shows all fields
function AllFieldsContent({ output, highlightFields = [] }: { output: Record<string, unknown>; highlightFields?: string[] }) {
  // Sort fields: highlighted first, then confidence scores, then others
  const sortedEntries = Object.entries(output).sort(([keyA], [keyB]) => {
    const aHighlight = highlightFields.includes(keyA);
    const bHighlight = highlightFields.includes(keyB);
    if (aHighlight && !bHighlight) return -1;
    if (!aHighlight && bHighlight) return 1;

    const aConfidence = keyA.includes('confidence');
    const bConfidence = keyB.includes('confidence');
    if (aConfidence && !bConfidence) return 1;
    if (!aConfidence && bConfidence) return -1;

    return keyA.localeCompare(keyB);
  });

  return (
    <div className="space-y-2">
      {sortedEntries.map(([key, value]) => {
        // Skip empty arrays and null values for cleaner display
        if (Array.isArray(value) && value.length === 0) return null;
        if (value === null || value === undefined || value === '') return null;

        const isHighlighted = highlightFields.includes(key);

        return (
          <div
            key={key}
            className={cn(
              "py-1 border-b border-border/30 last:border-0",
              isHighlighted && "bg-primary/5 -mx-2 px-2 rounded"
            )}
          >
            <div className="flex items-start gap-2">
              <span className={cn(
                "text-xs font-medium min-w-[120px] shrink-0",
                isHighlighted ? "text-primary" : "text-muted-foreground"
              )}>
                {formatLabel(key)}:
              </span>
              <div className="text-sm flex-1">{renderValue(value)}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function DemographicsContent({ output }: { output: Record<string, unknown> }) {
  return (
    <AllFieldsContent
      output={output}
      highlightFields={['age', 'gender', 'location', 'location_near']}
    />
  );
}

function PreferencesContent({ output }: { output: Record<string, unknown> }) {
  return (
    <AllFieldsContent
      output={output}
      highlightFields={['compatibility_score', 'preferred_kinks_found', 'preferred_hobbies_found', 'kinks', 'hobbies']}
    />
  );
}

function RelationshipGoalsContent({ output }: { output: Record<string, unknown> }) {
  return (
    <AllFieldsContent
      output={output}
      highlightFields={['relationship_intent', 'relationship_goals', 'partner_max_age', 'deal_breakers', 'partner_criteria']}
    />
  );
}

function RiskFlagsContent({ output }: { output: Record<string, unknown> }) {
  return (
    <AllFieldsContent
      output={output}
      highlightFields={['is_authentic', 'assessment', 'red_flags', 'scam_indicators']}
    />
  );
}

function SexualPreferencesContent({ output }: { output: Record<string, unknown> }) {
  return (
    <AllFieldsContent
      output={output}
      highlightFields={['ds_orientation', 'kinks_interests', 'intimacy_expectations', 'sexual_compatibility_notes']}
    />
  );
}

export function DimensionCard({ dimension, result }: DimensionCardProps) {
  const [expanded, setExpanded] = useState(true);
  const config = DIMENSION_CONFIG[dimension];

  if (!config) return null;

  const hasOutput = result.output && Object.keys(result.output).length > 0;
  const hasFailed = result.status === 'failed';

  const renderContent = () => {
    if (hasFailed) {
      return (
        <div className="text-center py-4">
          <XCircle className="h-6 w-6 text-destructive mx-auto mb-2" />
          <p className="text-sm text-muted-foreground">
            {result.error || 'Analysis failed for this dimension'}
          </p>
        </div>
      );
    }

    if (!hasOutput) {
      return (
        <p className="text-sm text-muted-foreground text-center py-4">
          No data available
        </p>
      );
    }

    switch (dimension) {
      case 'demographics':
        return <DemographicsContent output={result.output!} />;
      case 'preferences':
        return <PreferencesContent output={result.output!} />;
      case 'relationship_goals':
        return <RelationshipGoalsContent output={result.output!} />;
      case 'risk_flags':
        return <RiskFlagsContent output={result.output!} />;
      case 'sexual_preferences':
        return <SexualPreferencesContent output={result.output!} />;
      default:
        return null;
    }
  };

  return (
    <Card className="overflow-hidden">
      <CardHeader
        className={cn('py-3 cursor-pointer', config.bgColor)}
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className={config.color}>{config.icon}</span>
            <CardTitle className="text-sm font-medium">{config.title}</CardTitle>
          </div>
          <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
            {expanded ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </Button>
        </div>
      </CardHeader>
      {expanded && (
        <CardContent className="pt-4">
          {renderContent()}
        </CardContent>
      )}
    </Card>
  );
}
