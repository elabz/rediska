'use client';

import { useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, Eye, AlertTriangle, Code } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { MarkdownText } from '@/components/ui/markdown-text';
import { cn } from '@/lib/utils';
import { DIMENSION_LABELS, type ModelInput } from '@/lib/evaluations';

// Section order and labels as assembled by BaseAnalysisAgent._build_agent_input
const SECTION_LABELS: Record<string, string> = {
  title: 'Title',
  body: 'Post body',
  profile_summary: 'Profile summary',
  interests_summary: 'Interests summary',
  character_summary: 'Character summary',
  account_metadata: 'Account metadata',
  recent_posts: 'Recent posts',
};
const SECTION_ORDER = Object.keys(SECTION_LABELS);

export interface ParsedSection {
  name: string;
  text: string;
}

/** Split an assembled agent prompt into its <tag>…</tag> sections. */
export function parseSections(prompt: string | null | undefined): ParsedSection[] {
  if (!prompt) return [];
  const out: ParsedSection[] = [];
  const re = /<([a-z_]+)>([\s\S]*?)<\/\1>/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(prompt)) !== null) {
    out.push({ name: m[1], text: m[2].trim() });
  }
  return out;
}

interface MergedSection extends ParsedSection {
  dims: string[];
}

/** Union of sections across dimensions, longest text wins, with the dims that received each. */
export function mergeSections(inputs: Record<string, ModelInput | null | undefined>): MergedSection[] {
  const byName = new Map<string, MergedSection>();
  for (const [dim, input] of Object.entries(inputs)) {
    if (!input?.prompt) continue;
    for (const s of parseSections(input.prompt)) {
      const existing = byName.get(s.name);
      if (!existing) {
        byName.set(s.name, { ...s, dims: [dim] });
      } else {
        if (s.text.length > existing.text.length) existing.text = s.text;
        if (!existing.dims.includes(dim)) existing.dims.push(dim);
      }
    }
  }
  return Array.from(byName.values()).sort(
    (a, b) => (SECTION_ORDER.indexOf(a.name) + 1 || 99) - (SECTION_ORDER.indexOf(b.name) + 1 || 99)
  );
}

const SOURCE_NOTE: Record<string, { label: string; note: string | null; warn: boolean }> = {
  stored: { label: 'exact input', note: null, warn: false },
  excerpt: {
    label: 'first 2,000 chars only',
    note: 'This analysis predates full input storage; only an excerpt was kept. Re-analyse the lead to capture the complete input.',
    warn: true,
  },
  reconstructed: {
    label: 'reconstructed',
    note: 'No prompt was kept for this scout post. Shown is the stored post text and summaries the agents were built from, not the exact assembled prompt.',
    warn: true,
  },
  unavailable: { label: 'unavailable', note: 'No input was stored.', warn: true },
};

function RecentPosts({ text }: { text: string }) {
  const items = text.split(/\n---\n/).map((t) => t.trim()).filter(Boolean);
  return (
    <ol className="space-y-2">
      {items.map((t, i) => (
        <li key={i} className="rounded border border-border/50 bg-background/60 p-2 text-sm whitespace-pre-wrap break-words">
          {t}
        </li>
      ))}
    </ol>
  );
}

function SectionBody({ name, text }: { name: string; text: string }) {
  if (name === 'recent_posts') return <RecentPosts text={text} />;
  if (name === 'account_metadata') {
    return <pre className="text-xs whitespace-pre-wrap font-mono">{text}</pre>;
  }
  if (name === 'title') return <p className="text-sm font-medium">{text}</p>;
  return <MarkdownText className="text-sm whitespace-pre-wrap break-words">{text}</MarkdownText>;
}

interface AgentInputSectionsProps {
  /** Per-dimension inputs (queue) or a single {dimension: input} (dimension card). */
  inputs: Record<string, ModelInput | null | undefined>;
  defaultOpen?: boolean;
  className?: string;
}

/**
 * Everything the agents received, as readable sections. Each section notes
 * which agents got it; the raw per-agent prompt is available underneath.
 * Content is verbatim (research-content-policy).
 */
export function AgentInputSections({ inputs, defaultOpen = true, className }: AgentInputSectionsProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [showRaw, setShowRaw] = useState(false);
  const [rawDim, setRawDim] = useState<string | null>(null);

  const dims = useMemo(() => Object.keys(inputs).filter((d) => inputs[d]), [inputs]);
  const merged = useMemo(() => mergeSections(inputs), [inputs]);
  const sources = new Set(dims.map((d) => inputs[d]?.source ?? 'unavailable'));
  const worst = ['unavailable', 'reconstructed', 'excerpt', 'stored'].find((s) => sources.has(s)) ?? 'unavailable';
  const meta = SOURCE_NOTE[worst];
  const totalChars = Math.max(0, ...dims.map((d) => inputs[d]?.total_chars ?? 0));
  const activeRaw = rawDim && inputs[rawDim] ? rawDim : dims[0] ?? null;

  if (dims.length === 0) return null;

  return (
    <div className={cn('rounded-md border border-border/60', className)} data-testid="agent-input-sections">
      <Button
        variant="ghost"
        size="sm"
        className="w-full justify-between h-8 px-2 text-xs font-medium"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="inline-flex items-center gap-2">
          <Eye className="h-3.5 w-3.5" />
          {dims.length > 1 ? 'What the agents saw' : 'What the agent saw'}
          <Badge
            variant="outline"
            className={cn('text-[10px] font-normal', meta.warn && 'text-amber-700 border-amber-500/40 dark:text-amber-300')}
          >
            {meta.warn && <AlertTriangle className="h-3 w-3 mr-1" />}
            {meta.label}
            {totalChars ? ` · up to ${totalChars.toLocaleString()} chars` : ''}
          </Badge>
        </span>
        {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
      </Button>

      {open && (
        <div className="border-t border-border/60 p-3 space-y-3">
          {meta.note && <p className="text-xs text-amber-700 dark:text-amber-300">{meta.note}</p>}

          {merged.length === 0 ? (
            <p className="text-xs text-muted-foreground">No structured sections found; see the raw prompt below.</p>
          ) : (
            merged.map((s) => (
              <section key={s.name} className="rounded-md bg-muted/30 p-3">
                <header className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                  <h5 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {SECTION_LABELS[s.name] ?? s.name.replace(/_/g, ' ')}
                  </h5>
                  {dims.length > 1 && (
                    <span className="flex flex-wrap gap-1" title="Agents that received this section">
                      {s.dims.map((d) => (
                        <Badge key={d} variant="secondary" className="text-[10px] font-normal px-1.5 py-0">
                          {DIMENSION_LABELS[d] ?? d}
                        </Badge>
                      ))}
                      {s.dims.length < dims.length && (
                        <span className="text-[10px] text-muted-foreground self-center">
                          not sent to {dims.filter((d) => !s.dims.includes(d)).map((d) => DIMENSION_LABELS[d] ?? d).join(', ')}
                        </span>
                      )}
                    </span>
                  )}
                </header>
                <div className="max-h-72 overflow-y-auto">
                  <SectionBody name={s.name} text={s.text} />
                </div>
              </section>
            ))
          )}

          {/* Raw per-agent prompt */}
          <div>
            <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => setShowRaw((r) => !r)}>
              <Code className="h-3.5 w-3.5 mr-1" />
              {showRaw ? 'Hide raw prompt' : 'Show raw prompt per agent'}
            </Button>
            {showRaw && activeRaw && (
              <div className="mt-2 space-y-2">
                {dims.length > 1 && (
                  <div className="flex flex-wrap gap-1.5">
                    {dims.map((d) => (
                      <button
                        key={d}
                        type="button"
                        onClick={() => setRawDim(d)}
                        className={cn(
                          'rounded-md border px-2 py-0.5 text-xs transition-colors hover:bg-muted',
                          activeRaw === d && 'bg-primary text-primary-foreground border-primary'
                        )}
                      >
                        {DIMENSION_LABELS[d] ?? d}
                        {inputs[d]?.total_chars ? ` · ${inputs[d]?.total_chars?.toLocaleString()}` : ''}
                      </button>
                    ))}
                  </div>
                )}
                <pre className="text-xs whitespace-pre-wrap break-words bg-muted/40 p-3 rounded max-h-[28rem] overflow-y-auto font-mono">
                  {inputs[activeRaw]?.prompt ?? 'Nothing to show.'}
                </pre>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
