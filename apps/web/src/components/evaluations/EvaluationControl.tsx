'use client';

import { useState } from 'react';
import { ClipboardCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { EvaluationBadge } from './EvaluationBadge';
import { EvaluationDialog } from './EvaluationDialog';
import type {
  EffectiveEvaluation,
  EvaluableDimension,
  ModelInput,
  SubjectType,
} from '@/lib/evaluations';

interface EvaluationControlProps {
  subjectType: SubjectType;
  subjectId: number;
  dimension: EvaluableDimension | null;
  evaluation: EffectiveEvaluation | null | undefined;
  agentRecommendation?: string | null;
  agentOutput?: Record<string, unknown> | null;
  modelInput?: ModelInput | null;
  onSaved?: (evaluation: EffectiveEvaluation) => void;
  size?: 'sm' | 'xs';
  className?: string;
}

/**
 * Badge + "Evaluate" button + dialog. Mounted on the recommendation card,
 * each dimension card, scout history post detail, and the review queue.
 */
export function EvaluationControl({
  subjectType,
  subjectId,
  dimension,
  evaluation,
  agentRecommendation,
  agentOutput,
  modelInput,
  onSaved,
  size = 'sm',
  className,
}: EvaluationControlProps) {
  const [open, setOpen] = useState(false);
  const [local, setLocal] = useState<EffectiveEvaluation | null | undefined>(undefined);
  const current = local !== undefined ? local : evaluation;

  return (
    <span className={className}>
      <span className="inline-flex items-center gap-2 flex-wrap">
        <EvaluationBadge evaluation={current} showEmpty onClick={() => setOpen(true)} />
        <Button
          variant="ghost"
          size="sm"
          className={size === 'xs' ? 'h-6 px-2 text-xs' : 'h-7 px-2 text-xs'}
          onClick={(e) => {
            e.stopPropagation();
            setOpen(true);
          }}
          aria-label={dimension ? `Evaluate ${dimension}` : 'Evaluate final verdict'}
        >
          <ClipboardCheck className="h-3.5 w-3.5 mr-1" />
          {current ? 'Re-evaluate' : 'Evaluate'}
        </Button>
      </span>
      <EvaluationDialog
        open={open}
        onOpenChange={setOpen}
        subjectType={subjectType}
        subjectId={subjectId}
        dimension={dimension}
        agentRecommendation={agentRecommendation}
        agentOutput={agentOutput}
        modelInput={modelInput}
        existing={current ?? null}
        onSaved={(saved) => {
          setLocal(saved);
          onSaved?.(saved);
        }}
      />
    </span>
  );
}
