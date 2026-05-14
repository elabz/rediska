'use client';

import { useCallback, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type { Message } from '../_types';

export interface UseMessageActionsResult {
  deletingMessages: Set<number>;
  retryingMessages: Set<number>;
  remoteDeletingMessages: Set<number>;
  batchDeleting: boolean;
  actionError: string | null;
  setActionError: (value: string | null) => void;
  deleteMessage: (messageId: number) => Promise<void>;
  retryMessage: (messageId: number) => Promise<void>;
  remoteDeleteMessage: (messageId: number) => Promise<void>;
  scrubConversation: () => Promise<{ deleted: number; failed: number } | null>;
}

interface UseMessageActionsOptions {
  conversationId: string;
  setMessages: Dispatch<SetStateAction<Message[]>>;
  startFastPoll: () => void;
  onMessageDeleted?: () => void;
  onRemoteDeleted?: () => void;
  onScrubbed?: () => void;
}

export function useMessageActions({
  conversationId,
  setMessages,
  startFastPoll,
  onMessageDeleted,
  onRemoteDeleted,
  onScrubbed,
}: UseMessageActionsOptions): UseMessageActionsResult {
  const [deletingMessages, setDeletingMessages] = useState<Set<number>>(new Set());
  const [retryingMessages, setRetryingMessages] = useState<Set<number>>(new Set());
  const [remoteDeletingMessages, setRemoteDeletingMessages] = useState<Set<number>>(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const deleteMessage = useCallback(async (messageId: number) => {
    setDeletingMessages(prev => {
      const next = new Set(prev);
      next.add(messageId);
      return next;
    });
    setActionError(null);
    try {
      const response = await fetch(
        `/api/core/conversations/${conversationId}/messages/${messageId}`,
        { method: 'DELETE', credentials: 'include' }
      );
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to delete message');
      }
      setMessages(prev => prev.filter(m => m.id !== messageId));
      onMessageDeleted?.();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to delete message');
    } finally {
      setDeletingMessages(prev => {
        const next = new Set(prev);
        next.delete(messageId);
        return next;
      });
    }
  }, [conversationId, setMessages, onMessageDeleted]);

  const retryMessage = useCallback(async (messageId: number) => {
    setRetryingMessages(prev => {
      const next = new Set(prev);
      next.add(messageId);
      return next;
    });
    try {
      const response = await fetch(
        `/api/core/conversations/${conversationId}/messages/${messageId}/retry`,
        { method: 'POST', credentials: 'include' }
      );
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to resend message');
      }
      setMessages(prev => prev.map(m =>
        m.id === messageId
          ? { ...m, remote_visibility: 'unknown', send_error: null }
          : m
      ));
      startFastPoll();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to resend message');
    } finally {
      setRetryingMessages(prev => {
        const next = new Set(prev);
        next.delete(messageId);
        return next;
      });
    }
  }, [conversationId, setMessages, startFastPoll]);

  const remoteDeleteMessage = useCallback(async (messageId: number) => {
    setRemoteDeletingMessages(prev => { const next = new Set(prev); next.add(messageId); return next; });
    try {
      const response = await fetch(
        `/api/core/conversations/${conversationId}/messages/${messageId}/remote-delete`,
        { method: 'POST', credentials: 'include' }
      );
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to delete from Reddit');
      }
      setMessages(prev => prev.map(m =>
        m.id === messageId ? { ...m, remote_visibility: 'deleted_by_author' } : m
      ));
      onRemoteDeleted?.();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to delete from Reddit');
    } finally {
      setRemoteDeletingMessages(prev => { const next = new Set(prev); next.delete(messageId); return next; });
    }
  }, [conversationId, setMessages, onRemoteDeleted]);

  const scrubConversation = useCallback(async () => {
    setBatchDeleting(true);
    try {
      const response = await fetch(
        `/api/core/conversations/${conversationId}/messages/remote-delete-batch`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ all: true }),
        }
      );
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to scrub conversation');
      }
      const result = await response.json();
      setMessages(prev => prev.map(m => {
        const item = result.results?.find((r: { message_id: number; success: boolean }) => r.message_id === m.id);
        if (item?.success) {
          return { ...m, remote_visibility: 'deleted_by_author' };
        }
        return m;
      }));
      onScrubbed?.();
      if (result.failed > 0) {
        setActionError(`Scrub partially completed: ${result.deleted} deleted, ${result.failed} failed`);
      }
      return { deleted: result.deleted as number, failed: result.failed as number };
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to scrub conversation');
      return null;
    } finally {
      setBatchDeleting(false);
    }
  }, [conversationId, setMessages, onScrubbed]);

  return {
    deletingMessages,
    retryingMessages,
    remoteDeletingMessages,
    batchDeleting,
    actionError,
    setActionError,
    deleteMessage,
    retryMessage,
    remoteDeleteMessage,
    scrubConversation,
  };
}
