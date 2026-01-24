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
  Search,
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
    description: 'Extracts author age, gender, and location (near/far)',
    icon: <User className="h-5 w-5" />,
    color: 'text-blue-500',
    bgColor: 'bg-blue-500/10',
  },
  preferences: {
    title: 'Preferences & Interests',
    description: 'Extracts hobbies and kinks with compatibility scoring',
    icon: <Heart className="h-5 w-5" />,
    color: 'text-pink-500',
    bgColor: 'bg-pink-500/10',
  },
  relationship_goals: {
    title: 'Relationship Goals',
    description: 'Determines intent, partner max age, deal-breakers, and criteria',
    icon: <Target className="h-5 w-5" />,
    color: 'text-purple-500',
    bgColor: 'bg-purple-500/10',
  },
  risk_flags: {
    title: 'Risk Assessment',
    description: 'Detects scams, sellers, and fake profiles (OF, TG, sugar)',
    icon: <AlertTriangle className="h-5 w-5" />,
    color: 'text-amber-500',
    bgColor: 'bg-amber-500/10',
  },
  sexual_preferences: {
    title: 'Intimacy & Compatibility',
    description: 'Analyzes D/s orientation, kinks, and intimacy expectations',
    icon: <Flame className="h-5 w-5" />,
    color: 'text-red-500',
    bgColor: 'bg-red-500/10',
  },
  meta_analysis: {
    title: 'Meta-Analysis Coordinator',
    description: 'Applies decision rules to determine suitability',
    icon: <Sparkles className="h-5 w-5" />,
    color: 'text-emerald-500',
    bgColor: 'bg-emerald-500/10',
  },
  scout_quick_analysis: {
    title: 'Scout Quick Analysis',
    description: 'Fast screening of posts for Scout Watch automatic monitoring',
    icon: <Search className="h-5 w-5" />,
    color: 'text-cyan-500',
    bgColor: 'bg-cyan-500/10',
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
  'scout_quick_analysis',
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
