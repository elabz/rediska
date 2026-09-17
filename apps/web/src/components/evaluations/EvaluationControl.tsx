'use client';

import { useState } from 'react';
import { ThumbsUp, ThumbsDown, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { EvaluationBadge } from './EvaluationBadge';
import { EvaluationDialog } from './EvaluationDialog';
import type {
  EffectiveEvaluation,
  EvaluableDimension,
  EvaluationCreatePayload,
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
 * Inline verdict: Agree saves in one click; Disagree opens the form (pre-set
 * to Disagree) so the reviewer can say what was wrong. Mounted on the
 * recommendation card, dimension cards, scout history posts, and the queue.
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
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [local, setLocal] = useState<EffectiveEvaluation | null | undefined>(undefined);
  const current = local !== undefined ? local : evaluation;

  const btn = size === 'xs' ? 'h-6 px-2 text-xs' : 'h-7 px-2.5 text-xs';

  const agree = async () => {
    setSaving(true);
    setError(null);
    const payload: EvaluationCreatePayload = {
      subject_type: subjectType,
      subject_id: subjectId,
      dimension,
      human_verdict: 'agree',
      corrected_value: null,
      reason_tags: [],
      missing_info: null,
      notes: null,
    };
    try {
      const response = await fetch('/api/core/evaluations', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Failed to save');
      }
      const saved: EffectiveEvaluation = {
        id: data.id,
        human_verdict: data.human_verdict,
        reason_tags: data.reason_tags ?? [],
        corrected_value: data.corrected_value ?? null,
        missing_info: data.missing_info ?? null,
        notes: data.notes ?? null,
        created_at: data.created_at,
      };
      setLocal(saved);
      onSaved?.(saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  return (
    <span className={className}>
      <span className="inline-flex items-center gap-1.5 flex-wrap">
        <EvaluationBadge evaluation={current} showEmpty />
        <Button
          variant="outline"
          size="sm"
          className={cn(btn, 'text-emerald-700 border-emerald-500/40 hover:bg-emerald-500/10 dark:text-emerald-300')}
          disabled={saving}
          onClick={(e) => {
            e.stopPropagation();
            agree();
          }}
          aria-label={dimension ? `Agree with ${dimension}` : 'Agree with final verdict'}
        >
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ThumbsUp className="h-3.5 w-3.5" />}
          <span className="ml-1">Agree</span>
        </Button>
        <Button
          variant="outline"
          size="sm"
          className={cn(btn, 'text-red-700 border-red-500/40 hover:bg-red-500/10 dark:text-red-300')}
          disabled={saving}
          onClick={(e) => {
            e.stopPropagation();
            setOpen(true);
          }}
          aria-label={dimension ? `Disagree with ${dimension}` : 'Disagree with final verdict'}
        >
          <ThumbsDown className="h-3.5 w-3.5" />
          <span className="ml-1">Disagree</span>
        </Button>
        {error && <span className="text-xs text-destructive">{error}</span>}
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
        initialVerdict="disagree"
        onSaved={(saved) => {
          setLocal(saved);
          onSaved?.(saved);
        }}
      />
    </span>
  );
}
