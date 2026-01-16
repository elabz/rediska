'use client';

import {
  User,
  Heart,
  Target,
  AlertTriangle,
  Flame,
  Sparkles,
  Edit,
  Clock,
  FileText,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

import type { AgentPrompt } from '../page';

interface AgentPromptListProps {
  prompts: Record<string, AgentPrompt>;
  onSelectAgent: (dimension: string) => void;
}

const AGENT_CONFIG: Record<string, {
  title: string;
  description: string;
  icon: React.ReactNode;
  color: string;
  bgColor: string;
}> = {
  demographics: {
    title: 'Demographics',
    description: 'Analyzes age, gender, location, and cultural indicators',
    icon: <User className="h-5 w-5" />,
    color: 'text-blue-500',
    bgColor: 'bg-blue-500/10',
  },
  preferences: {
    title: 'Preferences & Interests',
    description: 'Identifies hobbies, lifestyle, values, and personality traits',
    icon: <Heart className="h-5 w-5" />,
    color: 'text-pink-500',
    bgColor: 'bg-pink-500/10',
  },
  relationship_goals: {
    title: 'Relationship Goals',
    description: 'Determines relationship intent, criteria, and compatibility factors',
    icon: <Target className="h-5 w-5" />,
    color: 'text-purple-500',
    bgColor: 'bg-purple-500/10',
  },
  risk_flags: {
    title: 'Risk Assessment',
    description: 'Identifies red flags, safety concerns, and authenticity indicators',
    icon: <AlertTriangle className="h-5 w-5" />,
    color: 'text-amber-500',
    bgColor: 'bg-amber-500/10',
  },
  sexual_preferences: {
    title: 'Intimacy & Compatibility',
    description: 'Analyzes orientation, preferences, and age preferences',
    icon: <Flame className="h-5 w-5" />,
    color: 'text-red-500',
    bgColor: 'bg-red-500/10',
  },
  meta_analysis: {
    title: 'Meta-Analysis Coordinator',
    description: 'Synthesizes all dimensions into final recommendation',
    icon: <Sparkles className="h-5 w-5" />,
    color: 'text-emerald-500',
    bgColor: 'bg-emerald-500/10',
  },
};

// Preferred order for display
const DIMENSION_ORDER = [
  'demographics',
  'preferences',
  'relationship_goals',
  'risk_flags',
  'sexual_preferences',
  'meta_analysis',
];

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function formatPromptLength(prompt: string): string {
  const chars = prompt.length;
  if (chars >= 1000) {
    return `${(chars / 1000).toFixed(1)}k chars`;
  }
  return `${chars} chars`;
}

export function AgentPromptList({ prompts, onSelectAgent }: AgentPromptListProps) {
  // Sort dimensions by preferred order
  const sortedDimensions = DIMENSION_ORDER.filter(d => prompts[d]);

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {sortedDimensions.map((dimension) => {
        const prompt = prompts[dimension];
        const config = AGENT_CONFIG[dimension];

        if (!config) return null;

        return (
          <Card
            key={dimension}
            className="cursor-pointer hover:border-primary/50 transition-colors"
            onClick={() => onSelectAgent(dimension)}
          >
            <CardHeader className="pb-2">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className={cn(
                    'flex h-10 w-10 items-center justify-center rounded-lg',
                    config.bgColor
                  )}>
                    <span className={config.color}>{config.icon}</span>
                  </div>
                  <div>
                    <CardTitle className="text-base">{config.title}</CardTitle>
                    <Badge variant="secondary" className="mt-1 text-xs">
                      v{prompt.version}
                    </Badge>
                  </div>
                </div>
                <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
                  <Edit className="h-4 w-4" />
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground mb-3">
                {config.description}
              </p>
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <div className="flex items-center gap-1">
                  <FileText className="h-3 w-3" />
                  <span>{formatPromptLength(prompt.system_prompt)}</span>
                </div>
                <div className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  <span>{formatDate(prompt.created_at)}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
