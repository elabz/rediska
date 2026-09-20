'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertCircle, Check, Loader2, X } from 'lucide-react';
import { Button } from '@/components/ui/button';

export interface CopySuggestion {
  id: number;
  provider_id: string;
  source_doc_type: string;
  source_entity_id: number;
  source_external_post_id: string;
  source_author: string | null;
  match_doc_type: string;
  match_entity_id: number;
  match_external_post_id: string;
  match_author: string | null;
  similarity: number;
  status: string;
}

export interface RewriteSuggestionsProps {
  /** The post this panel sits on; suggestions on either side are shown. */
  externalPostId: string;
  providerId?: string;
}

async function decide(id: number, action: 'accept' | 'reject'): Promise<string> {
  const response = await fetch(`/api/core/copy-suggestions/${id}/${action}`, {
    method: 'POST',
    credentials: 'include',
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    throw new Error(
      typeof detail === 'string' ? detail : detail?.error || 'Failed to record the decision',
    );
  }
  return data?.message ?? 'Recorded.';
}

/**
 * "This reads like an older ad by someone else." Semantic near-copies that the
 * fingerprint matcher cannot see, because the words differ. Each one waits for
 * the user: accepting joins the posts into a copy cluster, rejecting says no
 * and stops the pair coming back.
 */
export function RewriteSuggestions({ externalPostId, providerId = 'reddit' }: RewriteSuggestionsProps) {
  const [items, setItems] = useState<CopySuggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        status: 'new',
        provider_id: providerId,
        external_post_id: externalPostId,
      });
      const response = await fetch(`/api/core/copy-suggestions?${params}`, {
        credentials: 'include',
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof data.detail === 'string' ? data.detail : 'Failed to load rewrite suggestions',
        );
      }
      setItems(data.items as CopySuggestion[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load rewrite suggestions');
    } finally {
      setLoading(false);
    }
  }, [externalPostId, providerId]);

  useEffect(() => {
    load();
  }, [load]);

  const act = async (id: number, action: 'accept' | 'reject') => {
    setBusyId(id);
    setError(null);
    try {
      setNotice(await decide(id, action));
      setItems((prev) => prev.filter((item) => item.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to record the decision');
    } finally {
      setBusyId(null);
    }
  };

  // A quiet component: no suggestions, nothing on the page.
  if (loading && items.length === 0) return null;
  if (!error && items.length === 0 && !notice) return null;

  return (
    <div
      data-testid="rewrite-suggestions"
      className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 space-y-2"
    >
      <div className="text-sm font-medium text-amber-700 dark:text-amber-300">
        Probable rewrite{items.length === 1 ? '' : 's'}
      </div>
      <p className="text-xs text-muted-foreground">
        Different words, the same offer. Accepting joins the posts into a copy cluster;
        nothing happens until you decide.
      </p>

      {error && (
        <div className="flex items-start gap-2 text-xs text-destructive">
          <AlertCircle className="h-3 w-3 mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {notice && <p className="text-xs text-muted-foreground">{notice}</p>}

      <ul className="space-y-2">
        {items.map((item) => {
          const otherIsSource = item.source_external_post_id !== externalPostId;
          const otherAuthor = otherIsSource ? item.source_author : item.match_author;
          const otherType = otherIsSource ? item.source_doc_type : item.match_doc_type;
          const otherId = otherIsSource ? item.source_entity_id : item.match_entity_id;
          return (
            <li
              key={item.id}
              data-testid="rewrite-suggestion"
              className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-background px-3 py-2 text-sm"
            >
              <span className="text-xs text-muted-foreground">
                {Math.round(item.similarity * 100)}% alike
              </span>
              {otherAuthor ? (
                <span className="font-medium">u/{otherAuthor}</span>
              ) : (
                <span className="text-muted-foreground">unknown author</span>
              )}
              {otherType === 'lead_post' && (
                <Link href={`/leads/${otherId}`} className="text-xs hover:underline">
                  Open lead
                </Link>
              )}
              <div className="ml-auto flex gap-1">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busyId === item.id}
                  onClick={() => act(item.id, 'accept')}
                >
                  {busyId === item.id ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Check className="h-3 w-3" />
                  )}
                  <span className="ml-1">Same ad</span>
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busyId === item.id}
                  onClick={() => act(item.id, 'reject')}
                >
                  <X className="h-3 w-3" />
                  <span className="ml-1">Not a copy</span>
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
