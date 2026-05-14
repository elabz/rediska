'use client';

import { useCallback, useEffect, useState } from 'react';
import type { ListSummary } from '../_types';

export interface UseConversationListsResult {
  lists: ListSummary[];
  memberOf: Set<number>;
  loading: boolean;
  toggle: (listId: number) => Promise<void>;
  createAndAdd: (name: string) => Promise<void>;
}

export function useConversationLists(conversationId: string): UseConversationListsResult {
  const [lists, setLists] = useState<ListSummary[]>([]);
  const [memberOf, setMemberOf] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(false);

  const fetchLists = useCallback(async () => {
    try {
      const res = await fetch('/api/core/lists', { credentials: 'include' });
      if (!res.ok) return;
      const data = await res.json();
      setLists(data.lists || []);

      const member = new Set<number>();
      for (const lst of (data.lists || []) as ListSummary[]) {
        const idsRes = await fetch(`/api/core/lists/${lst.id}/conversation-ids`, { credentials: 'include' });
        if (idsRes.ok) {
          const idsData = await idsRes.json();
          if ((idsData.conversation_ids || []).includes(Number(conversationId))) {
            member.add(lst.id);
          }
        }
      }
      setMemberOf(member);
    } catch {
      // silent
    }
  }, [conversationId]);

  useEffect(() => {
    fetchLists();
  }, [fetchLists]);

  const toggle = useCallback(async (listId: number) => {
    const isInList = memberOf.has(listId);
    try {
      const res = await fetch(`/api/core/lists/${listId}/conversations/${conversationId}`, {
        method: isInList ? 'DELETE' : 'POST',
        credentials: 'include',
      });
      if (res.ok) {
        setMemberOf(prev => {
          const next = new Set(prev);
          if (isInList) next.delete(listId);
          else next.add(listId);
          return next;
        });
      }
    } catch {
      // silent
    }
  }, [conversationId, memberOf]);

  const createAndAdd = useCallback(async (name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setLoading(true);
    try {
      const res = await fetch('/api/core/lists', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: trimmed }),
      });
      if (res.ok) {
        const created = await res.json();
        await fetch(`/api/core/lists/${created.id}/conversations/${conversationId}`, {
          method: 'POST',
          credentials: 'include',
        });
        await fetchLists();
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [conversationId, fetchLists]);

  return { lists, memberOf, loading, toggle, createAndAdd };
}
