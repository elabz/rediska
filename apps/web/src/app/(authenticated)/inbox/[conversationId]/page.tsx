'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { AlertCircle, ArrowLeft, X } from 'lucide-react';
import { UserProfilePanel } from '@/components/UserProfilePanel';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import type { ConversationDetail, Message } from './_types';
import { MessagesSkeleton } from './_components/MessagesSkeleton';
import { ConversationHeader } from './_components/ConversationHeader';
import { MessageList, type MessageListHandle } from './_components/MessageList';
import { ComposeBox } from './_components/ComposeBox';
import { DeleteMessageDialog } from './_components/DeleteMessageDialog';
import { RemoteDeleteDialog } from './_components/RemoteDeleteDialog';
import { ScrubConversationDialog } from './_components/ScrubConversationDialog';
import { useMessages } from './_hooks/useMessages';
import { useMessageActions } from './_hooks/useMessageActions';

export default function ConversationDetailPage() {
  const params = useParams();
  const router = useRouter();
  const conversationId = params.conversationId as string;

  const [conversation, setConversation] = useState<ConversationDetail | null>(null);
  const [conversationLoading, setConversationLoading] = useState(true);
  const [conversationError, setConversationError] = useState<string | null>(null);
  const [messageToDelete, setMessageToDelete] = useState<number | null>(null);
  const [remoteDeleteTarget, setRemoteDeleteTarget] = useState<number | null>(null);
  const [showBatchDeleteDialog, setShowBatchDeleteDialog] = useState(false);

  const messageListRef = useRef<MessageListHandle>(null);

  const {
    messages,
    setMessages,
    loading: messagesLoading,
    error: messagesError,
    hasMore,
    loadingOlder,
    loadOlder,
    startFastPoll,
  } = useMessages(conversationId);

  const {
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
  } = useMessageActions({
    conversationId,
    setMessages,
    startFastPoll,
    onMessageDeleted: () => setMessageToDelete(null),
    onRemoteDeleted: () => setRemoteDeleteTarget(null),
    onScrubbed: () => setShowBatchDeleteDialog(false),
  });

  const loading = conversationLoading || messagesLoading;
  const error = conversationError ?? messagesError;

  const scrubEligibleCount = useMemo(
    () => messages.filter(m => m.direction === 'out' && m.remote_visibility === 'visible' && !!m.external_message_id).length,
    [messages]
  );

  const redditComposeUrl = useMemo(() => {
    if (!conversation) return '';
    const qs = new URLSearchParams({ to: conversation.counterpart.external_username });
    if (conversation.counterpart_last_post_title) {
      qs.set('subject', conversation.counterpart_last_post_title);
    }
    return `https://www.reddit.com/message/compose/?${qs.toString()}`;
  }, [conversation]);

  const handleMessageSent = useCallback((optimisticMessage: Message) => {
    setMessages(prev => [...prev, optimisticMessage]);
    setTimeout(() => messageListRef.current?.scrollToBottom(), 100);
    startFastPoll();
  }, [setMessages, startFastPoll]);

  const handleToggleStar = useCallback(async () => {
    if (!conversation) return;
    try {
      const response = await fetch(`/api/core/directories/${conversation.counterpart.id}/star`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!response.ok) return;
      const result = await response.json();
      setConversation(prev =>
        prev ? { ...prev, counterpart: { ...prev.counterpart, is_starred: result.is_starred } } : prev
      );
    } catch (err) {
      console.error('Failed to toggle star:', err);
    }
  }, [conversation]);

  useEffect(() => {
    let cancelled = false;
    const fetchConversation = async () => {
      setConversationLoading(true);
      setConversationError(null);
      try {
        const res = await fetch(`/api/core/conversations/${conversationId}`, { credentials: 'include' });
        if (!res.ok) {
          if (res.status === 404) throw new Error('Conversation not found');
          if (res.status === 401) throw new Error('Please log in to view this conversation');
          const data = await res.json();
          throw new Error(data.detail || 'Failed to load conversation');
        }
        const data: ConversationDetail = await res.json();
        if (!cancelled) setConversation(data);
      } catch (err) {
        if (!cancelled) setConversationError(err instanceof Error ? err.message : 'An error occurred');
      } finally {
        if (!cancelled) setConversationLoading(false);
      }
    };
    fetchConversation();
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  useEffect(() => {
    if (!loading && messages.length > 0) {
      messageListRef.current?.scrollToBottom();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  if (loading) {
    return (
      <div className="flex flex-col h-[calc(100vh-3.5rem)] lg:h-screen bg-card overflow-hidden">
        <div className="flex items-center gap-4 p-4 border-b border-border shrink-0">
          <Link href="/inbox">
            <Button variant="ghost" size="icon">
              <ArrowLeft className="h-5 w-5" />
            </Button>
          </Link>
          <Skeleton className="h-10 w-10 rounded-full" />
          <div className="space-y-1.5">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-3 w-20" />
          </div>
        </div>
        <MessagesSkeleton />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col h-[calc(100vh-3.5rem)] lg:h-screen bg-card overflow-hidden">
        <div className="flex items-center gap-4 p-4 border-b border-border shrink-0">
          <Link href="/inbox">
            <Button variant="ghost" size="icon">
              <ArrowLeft className="h-5 w-5" />
            </Button>
          </Link>
          <span className="font-medium">Conversation</span>
        </div>
        <div className="flex-1 flex items-center justify-center">
          <Card className="p-8 text-center max-w-md">
            <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
            <p className="text-destructive mb-4">{error}</p>
            <div className="flex gap-2 justify-center">
              <Button variant="outline" onClick={() => router.push('/inbox')}>Back to Inbox</Button>
              <Button onClick={() => window.location.reload()}>Try Again</Button>
            </div>
          </Card>
        </div>
      </div>
    );
  }

  if (!conversation) return null;

  return (
    <div className="flex flex-col h-[calc(100vh-10rem)] min-h-[400px] border border-border rounded-lg bg-card overflow-hidden">
      <ConversationHeader
        conversation={conversation}
        conversationId={conversationId}
        redditComposeUrl={redditComposeUrl}
        scrubEligibleCount={scrubEligibleCount}
        onToggleStar={handleToggleStar}
        onScrubRequest={() => setShowBatchDeleteDialog(true)}
      />

      <div className="px-4 pb-3 border-b border-border">
        <UserProfilePanel
          username={conversation.counterpart.external_username}
          accountId={conversation.counterpart.id}
          compact
        />
      </div>

      <MessageList
        ref={messageListRef}
        messages={messages}
        conversation={conversation}
        redditComposeUrl={redditComposeUrl}
        hasMore={hasMore}
        loadingOlder={loadingOlder}
        onLoadOlder={loadOlder}
        onDeleteMessage={setMessageToDelete}
        onRetryMessage={retryMessage}
        onRemoteDeleteMessage={setRemoteDeleteTarget}
        deletingMessages={deletingMessages}
        retryingMessages={retryingMessages}
        remoteDeletingMessages={remoteDeletingMessages}
      />

      {actionError && (
        <div className="mx-4 mt-4 rounded-lg border border-destructive bg-destructive/10 p-3">
          <div className="flex items-start gap-2">
            <AlertCircle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-sm font-medium text-destructive">Action failed</p>
              <p className="text-sm text-destructive/80 mt-1">{actionError}</p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setActionError(null)} className="h-6 w-6 p-0">
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}

      <ComposeBox
        conversationId={conversationId}
        counterpart={conversation.counterpart}
        identityId={conversation.identity_id}
        onSent={handleMessageSent}
      />

      <DeleteMessageDialog
        messageId={messageToDelete}
        isDeleting={messageToDelete !== null && deletingMessages.has(messageToDelete)}
        onCancel={() => setMessageToDelete(null)}
        onConfirm={deleteMessage}
      />

      <RemoteDeleteDialog
        messageId={remoteDeleteTarget}
        isDeleting={remoteDeleteTarget !== null && remoteDeletingMessages.has(remoteDeleteTarget)}
        onCancel={() => setRemoteDeleteTarget(null)}
        onConfirm={remoteDeleteMessage}
      />

      <ScrubConversationDialog
        open={showBatchDeleteDialog}
        eligibleCount={scrubEligibleCount}
        isScrubbing={batchDeleting}
        onCancel={() => setShowBatchDeleteDialog(false)}
        onConfirm={scrubConversation}
      />
    </div>
  );
}
