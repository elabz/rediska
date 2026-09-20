'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertCircle, Ban, Loader2, Sparkles } from 'lucide-react';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  AUTHOR_MODE_LABELS,
  DOC_TYPE_LABELS,
  LEAD_STATUS_STYLE,
  RECOMMENDATION_STYLE,
  fetchSimilar,
  hitHref,
  similarityPercent,
  type AuthorMode,
  type SimilarHit,
  type SimilarResponse,
} from '@/lib/similar';
import { cn } from '@/lib/utils';

const TYPE_FILTERS: { value: string; label: string; types: string[] | undefined }[] = [
  { value: 'all', label: 'Everything', types: undefined },
  { value: 'posts', label: 'Posts', types: ['lead_post', 'scout_post', 'profile_item'] },
  { value: 'leads', label: 'Leads', types: ['lead_post'] },
  { value: 'messages', label: 'Messages', types: ['message'] },
];

const AUTHOR_MODES: AuthorMode[] = ['any', 'other', 'same'];

export interface SimilarPanelProps {
  /** Reference document: what the neighbours are measured against. */
  docType: string;
  entityId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Shown in the header so the user knows what they asked about. */
  title?: string | null;
}

function formatDay(value: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString();
}

export function SimilarHitRow({ hit }: { hit: SimilarHit }) {
  const href = hitHref(hit);
  const percent = similarityPercent(hit);
  const name = hit.author_username;

  return (
    <li
      data-testid="similar-hit"
      className="rounded-md border border-border px-3 py-2 text-sm space-y-1"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="h-5 px-1.5 text-xs">
          {DOC_TYPE_LABELS[hit.doc_type] ?? hit.doc_type}
        </Badge>
        {percent && (
          <span className="text-xs text-muted-foreground" title="Cosine similarity">
            {percent} alike
          </span>
        )}
        {name ? (
          hit.account_id ? (
            <Link href={`/profile/${hit.account_id}`} className="font-medium hover:underline">
              u/{name}
            </Link>
          ) : (
            <span className="font-medium">u/{name}</span>
          )
        ) : (
          <span className="text-muted-foreground">unknown author</span>
        )}
        {hit.author_banned && (
          <span
            className="inline-flex items-center gap-1 text-xs text-red-700 dark:text-red-300"
            title="This author is on the do-not-contact list"
          >
            <Ban className="h-3 w-3" />
            banned
          </span>
        )}
        {hit.location && (
          <span className="text-xs text-muted-foreground">r/{hit.location}</span>
        )}
        {hit.created_at && (
          <span className="text-xs text-muted-foreground">{formatDay(hit.created_at)}</span>
        )}
      </div>

      {hit.title && <div className="font-medium">{hit.title}</div>}
      {hit.excerpt && (
        <p className="text-xs text-muted-foreground line-clamp-3">{hit.excerpt}</p>
      )}

      <div className="flex flex-wrap items-center gap-2 text-xs">
        {hit.lead_status && (
          <span
            className={cn(
              'rounded-md border px-1.5 py-0.5',
              LEAD_STATUS_STYLE[hit.lead_status] ?? 'border-border text-muted-foreground',
            )}
          >
            {hit.lead_status}
          </span>
        )}
        {hit.recommendation && (
          <span className={RECOMMENDATION_STYLE[hit.recommendation] ?? 'text-muted-foreground'}>
            {hit.recommendation.replace('_', ' ')}
          </span>
        )}
        {hit.human_verdict && (
          <span className="text-muted-foreground">you: {hit.human_verdict}</span>
        )}
        {href && (
          <Link href={href} className="ml-auto hover:underline">
            Open
          </Link>
        )}
      </div>
    </li>
  );
}

/**
 * "What else reads like this?" — the nearest indexed documents, with what
 * became of each one. The outcome is the point: a post that reads like three
 * leads you ignored is worth less of your time.
 */
export function SimilarPanel({ docType, entityId, open, onOpenChange, title }: SimilarPanelProps) {
  const [data, setData] = useState<SimilarResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState('all');
  const [author, setAuthor] = useState<AuthorMode>('any');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const types = TYPE_FILTERS.find((f) => f.value === typeFilter)?.types;
      setData(
        await fetchSimilar({
          doc_type: docType,
          entity_id: entityId,
          doc_types: types,
          author,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load similar content');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [docType, entityId, typeFilter, author]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const results = data?.results ?? [];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-2xl overflow-y-auto" data-testid="similar-panel">
        <SheetHeader>
          <SheetTitle>Similar content</SheetTitle>
          <SheetDescription>
            {title ? `Neighbours of “${title}”. ` : ''}
            Ranked by meaning, with what became of each one. Nothing here changes a
            lead or an analysis.
          </SheetDescription>
        </SheetHeader>

        <div className="mt-4 flex flex-wrap gap-2">
          {TYPE_FILTERS.map((filter) => (
            <Button
              key={filter.value}
              size="sm"
              variant={typeFilter === filter.value ? 'default' : 'outline'}
              onClick={() => setTypeFilter(filter.value)}
            >
              {filter.label}
            </Button>
          ))}
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          {AUTHOR_MODES.map((mode) => (
            <Button
              key={mode}
              size="sm"
              variant={author === mode ? 'default' : 'outline'}
              onClick={() => setAuthor(mode)}
            >
              {AUTHOR_MODE_LABELS[mode]}
            </Button>
          ))}
        </div>

        {data?.method === 'text' && (
          <p
            data-testid="similar-text-notice"
            className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-700 dark:text-amber-300"
          >
            No vector was available for this one, so these are word matches, not
            meaning matches.
          </p>
        )}

        {loading && (
          <div className="flex items-center justify-center h-40">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}

        {error && !loading && (
          <div
            data-testid="similar-error"
            className="mt-4 flex items-start gap-2 rounded-md border border-red-500/40 bg-red-500/5 px-3 py-2 text-sm text-red-700 dark:text-red-300"
          >
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            <div className="space-y-2">
              <p>{error}</p>
              <Button size="sm" variant="outline" onClick={load}>
                Try again
              </Button>
            </div>
          </div>
        )}

        {!loading && !error && results.length === 0 && (
          <p data-testid="similar-empty" className="mt-6 text-sm text-muted-foreground">
            Nothing else in the corpus reads like this one
            {data ? ` above ${Math.round(data.min_score * 100)}% similarity` : ''}.
          </p>
        )}

        {!loading && results.length > 0 && (
          <ul className="mt-4 space-y-2">
            {results.map((hit) => (
              <SimilarHitRow key={hit.id} hit={hit} />
            ))}
          </ul>
        )}
      </SheetContent>
    </Sheet>
  );
}

export interface SimilarButtonProps {
  docType: string;
  entityId: number;
  title?: string | null;
  className?: string;
  /** Compact icon-and-word trigger for list rows. */
  compact?: boolean;
}

/** "Similar" trigger that carries its own panel. Safe inside links and cards. */
export function SimilarButton({
  docType,
  entityId,
  title,
  className,
  compact = false,
}: SimilarButtonProps) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        data-testid="similar-button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen(true);
        }}
        title="Find content that reads like this"
        className={cn(
          'inline-flex items-center gap-1 rounded-md border border-border px-1.5 py-0.5',
          'text-xs font-medium text-muted-foreground',
          'hover:opacity-80 focus:outline-none focus:ring-2 focus:ring-ring',
          className,
        )}
      >
        <Sparkles className="h-3 w-3" />
        {compact ? 'Similar' : 'Similar content'}
      </button>
      {open && (
        <span onClick={(e) => e.stopPropagation()}>
          <SimilarPanel
            docType={docType}
            entityId={entityId}
            open={open}
            onOpenChange={setOpen}
            title={title}
          />
        </span>
      )}
    </>
  );
}
