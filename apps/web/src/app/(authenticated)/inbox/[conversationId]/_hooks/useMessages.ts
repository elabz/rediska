'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type { Message, MessagesResponse } from '../_types';
import { normalizeUtc } from '../_utils/timeFormat';

export interface UseMessagesResult {
  messages: Message[];
  setMessages: Dispatch<SetStateAction<Message[]>>;
  loading: boolean;
  error: string | null;
  hasMore: boolean;
  loadingOlder: boolean;
  loadOlder: () => Promise<void>;
  startFastPoll: () => void;
}

const SAFETY_LIMIT = 5000;
const NORMAL_POLL_INTERVAL_MS = 10_000;
const FAST_POLL_INTERVAL_MS = 2_000;
const FAST_POLL_DURATION_MS = 30_000;

export function useMessages(conversationId: string): UseMessagesResult {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [isFastPolling, setIsFastPolling] = useState(false);

  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const fastPollTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const fetchMessagesPage = useCallback(async (cursor?: string) => {
    const params = new URLSearchParams({ limit: '100' });
    if (cursor) {
      params.set('cursor', cursor);
    }

    const response = await fetch(
      `/api/core/conversations/${conversationId}/messages?${params.toString()}`,
      { credentials: 'include' }
    );

    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.detail || 'Failed to load messages');
    }

    return response.json() as Promise<MessagesResponse>;
  }, [conversationId]);

  const fetchAllMessages = useCallback(async (): Promise<{ messages: Message[]; nextCursor: string | null; hasMore: boolean }> => {
    const allMessages: Message[] = [];
    let cursor: string | undefined = undefined;
    let hasMoreLocal = true;

    while (hasMoreLocal) {
      const page = await fetchMessagesPage(cursor);
      allMessages.push(...page.messages);
      cursor = page.next_cursor || undefined;
      hasMoreLocal = page.has_more;

      if (allMessages.length > SAFETY_LIMIT) {
        return {
          messages: allMessages,
          nextCursor: cursor || null,
          hasMore: hasMoreLocal,
        };
      }
    }

    return { messages: allMessages, nextCursor: null, hasMore: false };
  }, [fetchMessagesPage]);

  const loadOlder = useCallback(async () => {
    if (!nextCursor || loadingOlder) return;

    setLoadingOlder(true);
    try {
      const msgsData = await fetchMessagesPage(nextCursor);
      const older = msgsData.messages.reverse();
      setMessages(prev => [...older, ...prev]);
      setNextCursor(msgsData.next_cursor);
      setHasMore(msgsData.has_more);
    } catch (err) {
      console.error('Failed to load older messages:', err);
    } finally {
      setLoadingOlder(false);
    }
  }, [nextCursor, loadingOlder, fetchMessagesPage]);

  const pollMessages = useCallback(async () => {
    try {
      const msgsData = await fetchMessagesPage();
      const freshMessages = msgsData.messages.reverse();

      setMessages(prev => {
        const updated: Message[] = [];
        const seenIds = new Set<number>();

        for (const existing of prev) {
          const fresh = freshMessages.find(f => f.id === existing.id);
          updated.push(fresh ?? existing);
          seenIds.add(existing.id);
        }

        for (const fresh of freshMessages) {
          if (!seenIds.has(fresh.id)) {
            updated.push(fresh);
          }
        }

        updated.sort((a, b) => new Date(normalizeUtc(a.sent_at)).getTime() - new Date(normalizeUtc(b.sent_at)).getTime());
        return updated;
      });
    } catch (err) {
      console.error('Failed to poll messages:', err);
    }
  }, [fetchMessagesPage]);

  const startFastPoll = useCallback(() => {
    if (fastPollTimeoutRef.current) {
      clearTimeout(fastPollTimeoutRef.current);
    }
    setIsFastPolling(true);
    fastPollTimeoutRef.current = setTimeout(() => {
      setIsFastPolling(false);
    }, FAST_POLL_DURATION_MS);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      setError(null);
      try {
        const msgsData = await fetchAllMessages();
        if (cancelled) return;
        setMessages(msgsData.messages.reverse());
        setNextCursor(msgsData.nextCursor);
        setHasMore(msgsData.hasMore);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'An error occurred');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [fetchAllMessages]);

  useEffect(() => {
    if (loading) return;
    const interval = isFastPolling ? FAST_POLL_INTERVAL_MS : NORMAL_POLL_INTERVAL_MS;
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }
    pollIntervalRef.current = setInterval(() => {
      pollMessages();
    }, interval);
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, [loading, isFastPolling, pollMessages]);

  useEffect(() => {
    const hasPending = messages.some(m => m.direction === 'out' && m.remote_visibility === 'unknown');
    if (isFastPolling && !hasPending) {
      if (fastPollTimeoutRef.current) {
        clearTimeout(fastPollTimeoutRef.current);
        fastPollTimeoutRef.current = null;
      }
      setIsFastPolling(false);
    }
  }, [isFastPolling, messages]);

  useEffect(() => {
    return () => {
      if (fastPollTimeoutRef.current) {
        clearTimeout(fastPollTimeoutRef.current);
      }
    };
  }, []);

  return {
    messages,
    setMessages,
    loading,
    error,
    hasMore,
    loadingOlder,
    loadOlder,
    startFastPoll,
  };
}
