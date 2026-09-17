'use client';

import { useEffect, useMemo, useState } from 'react';
import { ThumbsUp, ThumbsDown, MinusCircle, Loader2, AlertCircle } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { AgentInputSections } from './AgentInputSections';
import {
  CORRECTION_FIELDS,
  DIMENSION_LABELS,
  REASON_TAGS,
  REASON_TAG_LABELS,
  RECOMMENDATIONS,
  RECOMMENDATION_LABELS,
  VERDICT_LABELS,
  parseList,
  validateEvaluation,
  type EffectiveEvaluation,
  type EvaluableDimension,
  type EvaluationCreatePayload,
  type HumanVerdict,
  type ModelInput,
  type ReasonTag,
  type Recommendation,
  type SubjectType,
} from '@/lib/evaluations';

export interface EvaluationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  subjectType: SubjectType;
  subjectId: number;
  /** null = final recommendation */
  dimension: EvaluableDimension | null;
  /** What the agent said (final: recommendation; dimension: parsed output). */
  agentRecommendation?: string | null;
  agentOutput?: Record<string, unknown> | null;
  /** Existing effective evaluation (pre-fills the form). */
  existing?: EffectiveEvaluation | null;
  /** What the agent received, shown verbatim inside the dialog. */
  modelInput?: ModelInput | null;
  /** Verdict to start from when opened (e.g. Disagree from the inline control). */
  initialVerdict?: HumanVerdict;
  onSaved?: (evaluation: EffectiveEvaluation) => void;
}

const VERDICT_OPTIONS: { value: HumanVerdict; icon: React.ReactNode; className: string }[] = [
  {
    value: 'agree',
    icon: <ThumbsUp className="h-4 w-4" />,
    className: 'data-[active=true]:bg-emerald-500/15 data-[active=true]:text-emerald-700 data-[active=true]:border-emerald-500/40 dark:data-[active=true]:text-emerald-300',
  },
  {
    value: 'partial',
    icon: <MinusCircle className="h-4 w-4" />,
    className: 'data-[active=true]:bg-amber-500/15 data-[active=true]:text-amber-700 data-[active=true]:border-amber-500/40 dark:data-[active=true]:text-amber-300',
  },
  {
    value: 'disagree',
    icon: <ThumbsDown className="h-4 w-4" />,
    className: 'data-[active=true]:bg-red-500/15 data-[active=true]:text-red-700 data-[active=true]:border-red-500/40 dark:data-[active=true]:text-red-300',
  },
];

function stringify(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return value.map(String).join(', ');
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

export function EvaluationDialog({
  open,
  onOpenChange,
  subjectType,
  subjectId,
  dimension,
  agentRecommendation,
  agentOutput,
  existing,
  modelInput,
  initialVerdict,
  onSaved,
}: EvaluationDialogProps) {
  const [verdict, setVerdict] = useState<HumanVerdict>('agree');
  const [tags, setTags] = useState<ReasonTag[]>([]);
  const [missingInfo, setMissingInfo] = useState('');
  const [notes, setNotes] = useState('');
  const [correctedRecommendation, setCorrectedRecommendation] = useState<Recommendation | ''>('');
  const [corrections, setCorrections] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fields = useMemo(() => (dimension ? CORRECTION_FIELDS[dimension] : []), [dimension]);
  const title = dimension ? DIMENSION_LABELS[dimension] : DIMENSION_LABELS.final;

  // Reset / pre-fill on open
  useEffect(() => {
    if (!open) return;
    setError(null);
    setSaving(false);
    setVerdict(initialVerdict ?? existing?.human_verdict ?? 'agree');
    setTags((existing?.reason_tags ?? []).filter((t): t is ReasonTag => (REASON_TAGS as readonly string[]).includes(t)));
    setMissingInfo(existing?.missing_info ?? '');
    setNotes(existing?.notes ?? '');
    const cv = existing?.corrected_value ?? {};
    if (dimension) {
      setCorrectedRecommendation('');
      const next: Record<string, string> = {};
      for (const f of fields) {
        if (cv[f.key] !== undefined) next[f.key] = stringify(cv[f.key]);
      }
      setCorrections(next);
    } else {
      setCorrections({});
      const rec = cv.recommendation;
      setCorrectedRecommendation(
        typeof rec === 'string' && RECOMMENDATIONS.includes(rec as Recommendation)
          ? (rec as Recommendation)
          : ''
      );
    }
  }, [open, existing, dimension, fields, initialVerdict]);

  const toggleTag = (tag: ReasonTag) => {
    setTags((prev) => (prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]));
  };

  const buildCorrectedValue = (): Record<string, unknown> | null => {
    if (verdict === 'agree') return null;
    if (!dimension) {
      return correctedRecommendation ? { recommendation: correctedRecommendation } : null;
    }
    const out: Record<string, unknown> = {};
    for (const f of fields) {
      const raw = corrections[f.key];
      if (raw === undefined || raw.trim() === '') continue;
      switch (f.kind) {
        case 'number': {
          const n = Number(raw);
          out[f.key] = Number.isFinite(n) ? n : raw;
          break;
        }
        case 'list':
          out[f.key] = parseList(raw);
          break;
        case 'bool':
          out[f.key] = raw === 'true';
          break;
        default:
          out[f.key] = raw;
      }
    }
    return Object.keys(out).length ? out : null;
  };

  const handleSave = async () => {
    const corrected_value = buildCorrectedValue();
    const payload: EvaluationCreatePayload = {
      subject_type: subjectType,
      subject_id: subjectId,
      dimension,
      human_verdict: verdict,
      corrected_value,
      reason_tags: tags,
      missing_info: missingInfo.trim() || null,
      notes: notes.trim() || null,
    };
    const problem = validateEvaluation(payload);
    if (problem) {
      setError(problem);
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const response = await fetch('/api/core/evaluations', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) {
        let message = 'Failed to save evaluation';
        if (typeof data.detail === 'string') message = data.detail;
        else if (Array.isArray(data.detail)) {
          message = data.detail.map((e: { msg?: string }) => e.msg || 'Validation error').join(', ');
        }
        throw new Error(message);
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
      onSaved?.(saved);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save evaluation');
    } finally {
      setSaving(false);
    }
  };

  const showMissingInfo = tags.includes('missing_context');
  const showCorrection = verdict !== 'agree';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Evaluate: {title}</DialogTitle>
          <DialogDescription>
            {dimension
              ? 'Did the agent read this dimension correctly? Your verdict never changes the analysis.'
              : 'Do you agree with the agent’s final recommendation? Your verdict never changes the lead.'}
          </DialogDescription>
        </DialogHeader>

        {/* What the agent said */}
        {(agentRecommendation || (agentOutput && Object.keys(agentOutput).length > 0)) && (
          <div className="rounded-md bg-muted/40 p-3 text-xs space-y-1">
            <div className="font-medium uppercase text-muted-foreground">Agent said</div>
            {!dimension && agentRecommendation && (
              <div className="text-sm capitalize">{agentRecommendation.replace('_', ' ')}</div>
            )}
            {dimension && agentOutput && (
              <div className="grid gap-0.5">
                {fields
                  .filter((f) => agentOutput[f.key] !== undefined)
                  .map((f) => (
                    <div key={f.key}>
                      <span className="text-muted-foreground">{f.label}:</span>{' '}
                      <span>{stringify(agentOutput[f.key]) || '—'}</span>
                    </div>
                  ))}
              </div>
            )}
          </div>
        )}

        {modelInput && (
          <AgentInputSections inputs={{ [dimension ?? 'context']: modelInput }} defaultOpen={false} />
        )}

        {/* Verdict */}
        <div className="space-y-2">
          <Label>Verdict</Label>
          <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Verdict">
            {VERDICT_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                role="radio"
                aria-checked={verdict === opt.value}
                data-active={verdict === opt.value}
                onClick={() => setVerdict(opt.value)}
                className={cn(
                  'flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors hover:bg-muted',
                  opt.className
                )}
              >
                {opt.icon}
                {VERDICT_LABELS[opt.value]}
              </button>
            ))}
          </div>
        </div>

        {/* Correction */}
        {showCorrection && (
          <div className="space-y-2">
            <Label>What should it have been? (optional)</Label>
            {!dimension ? (
              <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Corrected recommendation">
                {RECOMMENDATIONS.map((rec) => (
                  <button
                    key={rec}
                    type="button"
                    role="radio"
                    aria-checked={correctedRecommendation === rec}
                    onClick={() => setCorrectedRecommendation(correctedRecommendation === rec ? '' : rec)}
                    className={cn(
                      'rounded-md border px-3 py-1.5 text-sm transition-colors hover:bg-muted',
                      correctedRecommendation === rec && 'bg-primary text-primary-foreground border-primary'
                    )}
                  >
                    {RECOMMENDATION_LABELS[rec]}
                  </button>
                ))}
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {fields.map((f) => (
                  <div key={f.key} className="space-y-1">
                    <Label htmlFor={`corr-${f.key}`} className="text-xs">
                      {f.label}
                    </Label>
                    {f.kind === 'select' || f.kind === 'bool' ? (
                      <select
                        id={`corr-${f.key}`}
                        value={corrections[f.key] ?? ''}
                        onChange={(e) => setCorrections((p) => ({ ...p, [f.key]: e.target.value }))}
                        className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm"
                      >
                        <option value="">(unchanged)</option>
                        {(f.kind === 'bool' ? ['true', 'false'] : f.options ?? []).map((o) => (
                          <option key={o} value={o}>
                            {o}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <Input
                        id={`corr-${f.key}`}
                        type={f.kind === 'number' ? 'number' : 'text'}
                        placeholder={f.placeholder}
                        value={corrections[f.key] ?? ''}
                        onChange={(e) => setCorrections((p) => ({ ...p, [f.key]: e.target.value }))}
                      />
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Reason tags */}
        <div className="space-y-2">
          <Label>Reasons</Label>
          <div className="flex flex-wrap gap-1.5">
            {REASON_TAGS.map((tag) => {
              const active = tags.includes(tag);
              return (
                <button
                  key={tag}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleTag(tag)}
                  className="focus:outline-none"
                >
                  <Badge
                    variant={active ? 'default' : 'outline'}
                    className={cn('cursor-pointer font-normal', !active && 'text-muted-foreground')}
                  >
                    {REASON_TAG_LABELS[tag]}
                  </Badge>
                </button>
              );
            })}
          </div>
        </div>

        {/* Missing info (required for missing_context) */}
        {showMissingInfo && (
          <div className="space-y-1">
            <Label htmlFor="missing-info">
              What information would have been needed? <span className="text-destructive">*</span>
            </Label>
            <Textarea
              id="missing-info"
              value={missingInfo}
              onChange={(e) => setMissingInfo(e.target.value)}
              placeholder="e.g. the author's home state was only in a comment reply"
              className="min-h-[60px]"
            />
          </div>
        )}

        {/* Notes */}
        <div className="space-y-1">
          <Label htmlFor="eval-notes">Notes (optional)</Label>
          <Textarea
            id="eval-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="min-h-[60px]"
          />
        </div>

        {error && (
          <div className="flex items-start gap-2 rounded-md border border-destructive bg-destructive/10 p-2 text-sm text-destructive" role="alert">
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
                Saving…
              </>
            ) : (
              'Save evaluation'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
