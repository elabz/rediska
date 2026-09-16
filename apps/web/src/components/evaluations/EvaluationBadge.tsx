'use client';

import { ThumbsUp, ThumbsDown, MinusCircle, CircleDashed } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import {
  REASON_TAG_LABELS,
  VERDICT_LABELS,
  type EffectiveEvaluation,
  type ReasonTag,
} from '@/lib/evaluations';

interface EvaluationBadgeProps {
  evaluation: EffectiveEvaluation | null | undefined;
  /** Show "Not evaluated" when null instead of rendering nothing. */
  showEmpty?: boolean;
  /** Show the reason tags after the verdict. */
  showTags?: boolean;
  className?: string;
  onClick?: () => void;
}

const VERDICT_STYLES = {
  agree: {
    icon: ThumbsUp,
    className: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/30 dark:text-emerald-300',
  },
  partial: {
    icon: MinusCircle,
    className: 'bg-amber-500/10 text-amber-700 border-amber-500/30 dark:text-amber-300',
  },
  disagree: {
    icon: ThumbsDown,
    className: 'bg-red-500/10 text-red-700 border-red-500/30 dark:text-red-300',
  },
} as const;

export function EvaluationBadge({
  evaluation,
  showEmpty = false,
  showTags = true,
  className,
  onClick,
}: EvaluationBadgeProps) {
  if (!evaluation) {
    if (!showEmpty) return null;
    return (
      <Badge
        variant="outline"
        className={cn('text-xs text-muted-foreground gap-1 font-normal', onClick && 'cursor-pointer', className)}
        onClick={onClick}
        data-testid="evaluation-badge-empty"
      >
        <CircleDashed className="h-3 w-3" />
        Not evaluated
      </Badge>
    );
  }

  const style = VERDICT_STYLES[evaluation.human_verdict] ?? VERDICT_STYLES.partial;
  const Icon = style.icon;
  const tags = showTags ? evaluation.reason_tags : [];

  return (
    <span className={cn('inline-flex flex-wrap items-center gap-1', className)}>
      <Badge
        variant="outline"
        className={cn('text-xs gap-1', style.className, onClick && 'cursor-pointer')}
        onClick={onClick}
        title={evaluation.notes || undefined}
        data-testid="evaluation-badge"
      >
        <Icon className="h-3 w-3" />
        {VERDICT_LABELS[evaluation.human_verdict] ?? evaluation.human_verdict}
      </Badge>
      {tags.map((tag) => (
        <Badge key={tag} variant="secondary" className="text-[10px] font-normal">
          {REASON_TAG_LABELS[tag as ReasonTag] ?? tag}
        </Badge>
      ))}
    </span>
  );
}
