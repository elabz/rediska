/**
 * Shared types and vocabulary for human evaluation of agent decisions.
 *
 * REASON_TAGS mirrors services/core/rediska_core/api/schemas/evaluations.py;
 * adding a tag is a code + spec change on both sides.
 */

export const REASON_TAGS = [
  'missed_location',
  'wrong_age',
  'wrong_gender',
  'misread_intent',
  'misread_orientation',
  'hallucinated_fact',
  'missing_context',
  'stale_context',
  'too_strict',
  'too_lenient',
  'unparseable_output',
  'risk_missed',
  'risk_overcalled',
  'other',
] as const;

export type ReasonTag = (typeof REASON_TAGS)[number];

export const REASON_TAG_LABELS: Record<ReasonTag, string> = {
  missed_location: 'Missed location',
  wrong_age: 'Wrong age',
  wrong_gender: 'Wrong gender',
  misread_intent: 'Misread intent',
  misread_orientation: 'Misread orientation',
  hallucinated_fact: 'Hallucinated fact',
  missing_context: 'Missing context',
  stale_context: 'Stale context',
  too_strict: 'Too strict',
  too_lenient: 'Too lenient',
  unparseable_output: 'Unparseable output',
  risk_missed: 'Risk missed',
  risk_overcalled: 'Risk overcalled',
  other: 'Other',
};

export const EVALUABLE_DIMENSIONS = [
  'demographics',
  'preferences',
  'relationship_goals',
  'risk_flags',
  'sexual_preferences',
] as const;

export type EvaluableDimension = (typeof EVALUABLE_DIMENSIONS)[number];

export const DIMENSION_LABELS: Record<string, string> = {
  final: 'Final verdict',
  demographics: 'Demographics',
  preferences: 'Preferences',
  relationship_goals: 'Relationship goals',
  risk_flags: 'Risk flags',
  sexual_preferences: 'Intimacy',
  meta_analysis: 'Meta-analysis',
};

export type HumanVerdict = 'agree' | 'partial' | 'disagree';
export type Recommendation = 'suitable' | 'not_recommended' | 'needs_review';
export type SubjectType = 'lead_analysis' | 'scout_post';

export const RECOMMENDATIONS: Recommendation[] = ['suitable', 'needs_review', 'not_recommended'];

export const RECOMMENDATION_LABELS: Record<Recommendation, string> = {
  suitable: 'Suitable',
  needs_review: 'Needs review',
  not_recommended: 'Not recommended',
};

export interface EffectiveEvaluation {
  id: number;
  human_verdict: HumanVerdict;
  reason_tags: string[];
  corrected_value: Record<string, unknown> | null;
  missing_info: string | null;
  notes: string | null;
  created_at: string;
}

export type EvaluationMap = Record<string, EffectiveEvaluation | null>;

/** Exactly what a dimension agent received (mirrors domain/schemas/evaluation.py ModelInput). */
export interface ModelInput {
  source: 'stored' | 'excerpt' | 'reconstructed' | 'unavailable' | string;
  prompt: string | null;
  sections: string[];
  total_chars: number | null;
  attempt: number | null;
}

export interface EvaluationCreatePayload {
  subject_type: SubjectType;
  subject_id: number;
  dimension: EvaluableDimension | null;
  human_verdict: HumanVerdict;
  corrected_value: Record<string, unknown> | null;
  reason_tags: ReasonTag[];
  missing_info: string | null;
  notes: string | null;
}

/** Correction fields shown per dimension (the canonical fields replay compares). */
export interface CorrectionField {
  key: string;
  label: string;
  kind: 'text' | 'number' | 'list' | 'select' | 'bool';
  options?: string[];
  placeholder?: string;
}

export const CORRECTION_FIELDS: Record<EvaluableDimension, CorrectionField[]> = {
  demographics: [
    { key: 'age', label: 'Age', kind: 'number', placeholder: 'e.g. 34' },
    {
      key: 'gender',
      label: 'Gender',
      kind: 'select',
      options: ['female', 'male', 'non-binary', 'unclear'],
    },
    {
      key: 'location_state',
      label: 'Location',
      kind: 'select',
      options: ['near', 'far', 'unclear'],
    },
    { key: 'location', label: 'Location text', kind: 'text', placeholder: 'e.g. Philadelphia' },
  ],
  preferences: [
    { key: 'kinks', label: 'Kinks', kind: 'list', placeholder: 'comma-separated' },
    { key: 'hobbies', label: 'Hobbies', kind: 'list', placeholder: 'comma-separated' },
    { key: 'lifestyle', label: 'Lifestyle', kind: 'text' },
  ],
  relationship_goals: [
    { key: 'relationship_intent', label: 'Intent', kind: 'text', placeholder: 'e.g. long-term' },
    { key: 'partner_max_age', label: 'Partner max age', kind: 'number' },
    { key: 'deal_breakers', label: 'Deal breakers', kind: 'list', placeholder: 'comma-separated' },
  ],
  risk_flags: [
    { key: 'is_authentic', label: 'Authentic', kind: 'bool' },
    { key: 'red_flags', label: 'Red flags', kind: 'list', placeholder: 'comma-separated' },
    { key: 'scam_indicators', label: 'Scam indicators', kind: 'list', placeholder: 'comma-separated' },
  ],
  sexual_preferences: [
    {
      key: 'ds_orientation',
      label: 'D/s orientation',
      kind: 'select',
      options: ['dominant', 'submissive', 'switch', 'unclear'],
    },
    { key: 'kinks_interests', label: 'Kinks / interests', kind: 'list', placeholder: 'comma-separated' },
  ],
};

export const VERDICT_LABELS: Record<HumanVerdict, string> = {
  agree: 'Agree',
  partial: 'Partially',
  disagree: 'Disagree',
};

/** Validation mirrored from the backend so the dialog can fail fast. */
export function validateEvaluation(input: {
  reason_tags: string[];
  missing_info: string | null;
  dimension: string | null;
  corrected_value: Record<string, unknown> | null;
}): string | null {
  if (input.reason_tags.includes('missing_context') && !(input.missing_info || '').trim()) {
    return 'Say what information would have been needed (required for "Missing context").';
  }
  if (input.dimension === null && input.corrected_value) {
    const rec = input.corrected_value.recommendation;
    if (rec !== undefined && !RECOMMENDATIONS.includes(rec as Recommendation)) {
      return 'Corrected recommendation must be suitable, needs review, or not recommended.';
    }
  }
  return null;
}

/** Parse a comma/newline separated list into trimmed strings. */
export function parseList(value: string): string[] {
  return value
    .split(/[,\n;]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function formatAgreement(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return `${Math.round(value * 100)}%`;
}
