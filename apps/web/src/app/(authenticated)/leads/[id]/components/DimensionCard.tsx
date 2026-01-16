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

function DemographicsContent({ output }: { output: Record<string, unknown> }) {
  const ageRange = output.age_range as [number, number] | null;
  const gender = output.gender as string | null;
  const location = output.location as string | null;

  return (
    <div className="space-y-3">
      {/* Age */}
      {ageRange && (
        <div className="flex items-center justify-between">
          <span className="text-sm">Age Range</span>
          <div className="flex items-center gap-2">
            <span className="font-medium">{ageRange[0]}-{ageRange[1]}</span>
            <ConfidenceMeter value={output.age_confidence as number || 0.5} />
          </div>
        </div>
      )}

      {/* Gender */}
      {gender && (
        <div className="flex items-center justify-between">
          <span className="text-sm">Gender</span>
          <div className="flex items-center gap-2">
            <span className="font-medium capitalize">{gender}</span>
            <ConfidenceMeter value={output.gender_confidence as number || 0.5} />
          </div>
        </div>
      )}

      {/* Location */}
      {location && (
        <div className="flex items-center justify-between">
          <span className="text-sm">Location</span>
          <div className="flex items-center gap-2">
            <MapPin className="h-3 w-3 text-muted-foreground" />
            <span className="font-medium">{location}</span>
            <ConfidenceMeter value={output.location_confidence as number || 0.5} />
          </div>
        </div>
      )}

      {/* Ethnicity indicators */}
      {(output.ethnicity_indicators as string[])?.length > 0 && (
        <div>
          <span className="text-xs text-muted-foreground">Cultural indicators</span>
          <TagList items={output.ethnicity_indicators as string[]} />
        </div>
      )}
    </div>
  );
}

function PreferencesContent({ output }: { output: Record<string, unknown> }) {
  const hobbies = output.hobbies as string[] || [];
  const values = output.values as string[] || [];
  const traits = output.personality_traits as string[] || [];
  const lifestyle = output.lifestyle as string | null;
  const commStyle = output.communication_style as string | null;

  return (
    <div className="space-y-3">
      {lifestyle && (
        <div className="flex items-center justify-between">
          <span className="text-sm">Lifestyle</span>
          <Badge variant="secondary" className="capitalize">{lifestyle}</Badge>
        </div>
      )}

      {commStyle && (
        <div className="flex items-center justify-between">
          <span className="text-sm">Communication</span>
          <Badge variant="secondary" className="capitalize">{commStyle}</Badge>
        </div>
      )}

      {hobbies.length > 0 && (
        <div>
          <span className="text-xs text-muted-foreground block mb-1">Hobbies</span>
          <TagList items={hobbies} />
        </div>
      )}

      {values.length > 0 && (
        <div>
          <span className="text-xs text-muted-foreground block mb-1">Values</span>
          <TagList items={values} color="success" />
        </div>
      )}

      {traits.length > 0 && (
        <div>
          <span className="text-xs text-muted-foreground block mb-1">Personality</span>
          <TagList items={traits} />
        </div>
      )}
    </div>
  );
}

function RelationshipGoalsContent({ output }: { output: Record<string, unknown> }) {
  const intent = output.relationship_intent as string | null;
  const timeline = output.relationship_timeline as string | null;
  const dealBreakers = output.deal_breakers as string[] || [];
  const compatibility = output.compatibility_factors as string[] || [];
  const incompatibility = output.incompatibility_factors as string[] || [];

  return (
    <div className="space-y-3">
      {intent && (
        <div className="flex items-center justify-between">
          <span className="text-sm">Intent</span>
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="capitalize">{intent}</Badge>
            <ConfidenceMeter value={output.intent_confidence as number || 0.5} />
          </div>
        </div>
      )}

      {timeline && (
        <div className="flex items-center justify-between">
          <span className="text-sm">Timeline</span>
          <Badge variant="outline" className="capitalize">{timeline}</Badge>
        </div>
      )}

      {dealBreakers.length > 0 && (
        <div>
          <span className="text-xs text-muted-foreground block mb-1">Deal Breakers</span>
          <TagList items={dealBreakers} color="danger" />
        </div>
      )}

      {compatibility.length > 0 && (
        <div>
          <span className="text-xs text-muted-foreground block mb-1">Compatibility Factors</span>
          <TagList items={compatibility} color="success" />
        </div>
      )}

      {incompatibility.length > 0 && (
        <div>
          <span className="text-xs text-muted-foreground block mb-1">Incompatibility Factors</span>
          <TagList items={incompatibility} color="warning" />
        </div>
      )}
    </div>
  );
}

function RiskFlagsContent({ output }: { output: Record<string, unknown> }) {
  const flags = output.flags as Array<{type: string; severity: string; description: string}> || [];
  const safetyAssessment = output.safety_assessment as string;
  const authenticityScore = output.authenticity_score as number;
  const overallRisk = output.overall_risk_level as string;
  const manipulationIndicators = output.manipulation_indicators as string[] || [];

  const severityColors: Record<string, string> = {
    low: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20',
    medium: 'bg-amber-500/10 text-amber-600 border-amber-500/20',
    high: 'bg-orange-500/10 text-orange-600 border-orange-500/20',
    critical: 'bg-red-500/10 text-red-600 border-red-500/20',
  };

  const riskColors: Record<string, string> = {
    low: 'text-emerald-600',
    medium: 'text-amber-600',
    high: 'text-orange-600',
    critical: 'text-red-600',
  };

  return (
    <div className="space-y-3">
      {/* Overall Risk Level */}
      {overallRisk && (
        <div className="flex items-center justify-between">
          <span className="text-sm">Overall Risk</span>
          <Badge
            variant="outline"
            className={cn('capitalize', severityColors[overallRisk])}
          >
            {overallRisk}
          </Badge>
        </div>
      )}

      {/* Safety Assessment */}
      {safetyAssessment && (
        <div className="flex items-center justify-between">
          <span className="text-sm">Safety</span>
          <div className="flex items-center gap-1">
            {safetyAssessment === 'safe' ? (
              <CheckCircle className="h-4 w-4 text-emerald-500" />
            ) : safetyAssessment === 'caution' ? (
              <AlertTriangle className="h-4 w-4 text-amber-500" />
            ) : (
              <XCircle className="h-4 w-4 text-red-500" />
            )}
            <span className={cn('font-medium capitalize', riskColors[safetyAssessment] || '')}>
              {safetyAssessment}
            </span>
          </div>
        </div>
      )}

      {/* Authenticity */}
      {authenticityScore !== undefined && (
        <div className="flex items-center justify-between">
          <span className="text-sm">Authenticity</span>
          <ConfidenceMeter value={authenticityScore} />
        </div>
      )}

      {/* Individual Flags */}
      {flags.length > 0 && (
        <div>
          <span className="text-xs text-muted-foreground block mb-2">Risk Flags</span>
          <div className="space-y-2">
            {flags.map((flag, idx) => (
              <div
                key={idx}
                className={cn(
                  'text-xs p-2 rounded border',
                  severityColors[flag.severity]
                )}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="font-medium capitalize">{flag.type.replace('_', ' ')}</span>
                  <Badge variant="outline" className={severityColors[flag.severity]}>
                    {flag.severity}
                  </Badge>
                </div>
                <p className="text-muted-foreground">{flag.description}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Manipulation Indicators */}
      {manipulationIndicators.length > 0 && (
        <div>
          <span className="text-xs text-muted-foreground block mb-1">Manipulation Indicators</span>
          <TagList items={manipulationIndicators} color="danger" />
        </div>
      )}
    </div>
  );
}

function SexualPreferencesContent({ output }: { output: Record<string, unknown> }) {
  const orientation = output.sexual_orientation as string | null;
  const partnerAgeRange = output.desired_partner_age_range as [number, number] | null;
  const kinks = output.kinks_interests as string[] || [];
  const intimacyExpectations = output.intimacy_expectations as string | null;
  const ageConcerns = output.age_gap_concerns as string[] || [];
  const compatibilityNotes = output.sexual_compatibility_notes as string[] || [];

  return (
    <div className="space-y-3">
      {orientation && (
        <div className="flex items-center justify-between">
          <span className="text-sm">Orientation</span>
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="capitalize">{orientation}</Badge>
            <ConfidenceMeter value={output.orientation_confidence as number || 0.5} />
          </div>
        </div>
      )}

      {partnerAgeRange && (
        <div className="flex items-center justify-between">
          <span className="text-sm">Seeks Age</span>
          <div className="flex items-center gap-2">
            <span className="font-medium">{partnerAgeRange[0]}-{partnerAgeRange[1]}</span>
            <ConfidenceMeter value={output.age_preference_confidence as number || 0.5} />
          </div>
        </div>
      )}

      {intimacyExpectations && (
        <div className="flex items-center justify-between">
          <span className="text-sm">Intimacy</span>
          <Badge variant="outline" className="capitalize">{intimacyExpectations}</Badge>
        </div>
      )}

      {kinks.length > 0 && (
        <div>
          <span className="text-xs text-muted-foreground block mb-1">Interests</span>
          <TagList items={kinks} />
        </div>
      )}

      {ageConcerns.length > 0 && (
        <div>
          <span className="text-xs text-muted-foreground block mb-1">Age Gap Concerns</span>
          <TagList items={ageConcerns} color="warning" />
        </div>
      )}

      {compatibilityNotes.length > 0 && (
        <div>
          <span className="text-xs text-muted-foreground block mb-1">Notes</span>
          <ul className="text-xs text-muted-foreground space-y-1">
            {compatibilityNotes.map((note, idx) => (
              <li key={idx}>• {note}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
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
