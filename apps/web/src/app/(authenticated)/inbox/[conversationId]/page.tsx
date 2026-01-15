'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, Loader2, Send, AlertCircle, ExternalLink, ChevronUp, ImageIcon, Download, MoreVertical, Trash2, X, Paperclip } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

interface Counterpart {
  id: number;
  external_username: string;
  external_user_id: string | null;
  remote_status: string;
}

interface ConversationDetail {
  id: number;
  provider_id: string;
  identity_id: number;
  external_conversation_id: string;
  counterpart: Counterpart;
  last_activity_at: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

interface Attachment {
  id: number;
  mime_type: string;
  size_bytes: number;
  width_px: number | null;
  height_px: number | null;
}

interface Message {
  id: number;
  direction: 'in' | 'out' | 'system';
  body_text: string | null;
  sent_at: string;
  remote_visibility: string;
  identity_id: number | null;
  created_at: string;
  attachments?: Attachment[];
}

interface MessagesResponse {
  messages: Message[];
  next_cursor: string | null;
  has_more: boolean;
}

function getInitials(username: string): string {
  return username.slice(0, 2).toUpperCase();
}

function formatMessageTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const isToday = date.toDateString() === now.toDateString();

  if (isToday) {
    return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  }

  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) {
    return `Yesterday ${date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}`;
  }

  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit'
  });
}

function MessageBubble({
  message,
  counterpartUsername,
  onDelete,
  isDeleting,
}: {
  message: Message;
  counterpartUsername: string;
  onDelete?: (messageId: number) => void;
  isDeleting?: boolean;
}) {
  const isOutgoing = message.direction === 'out';
  const isSystem = message.direction === 'system';
  const [imageErrors, setImageErrors] = useState<Set<number>>(new Set());
  const isPending = message.remote_visibility === 'unknown';
  const canDelete = isOutgoing && isPending && onDelete;

  const imageAttachments = (message.attachments || []).filter(att => att.mime_type.startsWith('image/'));

  if (isSystem) {
    return (
      <div className="flex justify-center my-4">
        <div className="bg-muted px-4 py-2 rounded-full text-sm text-muted-foreground">
          {message.body_text}
        </div>
      </div>
    );
  }

  return (
    <div className={cn(
      "flex gap-3 mb-4 group",
      isOutgoing ? "flex-row-reverse" : "flex-row"
    )}>
      {!isOutgoing && (
        <Avatar className="h-8 w-8 shrink-0">
          <AvatarFallback className="bg-muted text-xs">
            {getInitials(counterpartUsername)}
          </AvatarFallback>
        </Avatar>
      )}

      <div className={cn(
        "flex flex-col max-w-[75%]",
        isOutgoing ? "items-end" : "items-start"
      )}>
        {/* Image attachments */}
        {imageAttachments.length > 0 && (
          <div className={cn(
            "flex flex-wrap gap-2 mb-2",
            isOutgoing ? "justify-end" : "justify-start"
          )}>
            {imageAttachments.map((att) => (
              <div key={att.id} className="relative">
                {imageErrors.has(att.id) ? (
                  <div className="w-48 h-32 bg-muted rounded-lg flex items-center justify-center">
                    <div className="text-center text-muted-foreground">
                      <ImageIcon className="h-8 w-8 mx-auto mb-1" />
                      <span className="text-xs">Image unavailable</span>
                    </div>
                  </div>
                ) : (
                  <a
                    href={`/api/core/attachments/${att.id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`/api/core/attachments/${att.id}`}
                      alt="Attachment"
                      className="max-w-[300px] max-h-[300px] rounded-lg object-contain cursor-pointer hover:opacity-90 transition-opacity"
                      style={{
                        width: att.width_px ? Math.min(att.width_px, 300) : 'auto',
                        height: att.height_px ? Math.min(att.height_px, 300) : 'auto',
                      }}
                      onError={() => setImageErrors(prev => { const next = new Set(prev); next.add(att.id); return next; })}
                    />
                  </a>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Message body */}
        {message.body_text && (
          <div className={cn(
            "px-4 py-2.5 rounded-2xl",
            isOutgoing
              ? "bg-primary text-primary-foreground rounded-br-sm"
              : "bg-muted rounded-bl-sm"
          )}>
            <p className="text-sm whitespace-pre-wrap break-words">
              {message.body_text}
            </p>
          </div>
        )}

        <div className="flex items-center gap-2 mt-1 px-1">
          <span className="text-xs text-muted-foreground">
            {formatMessageTime(message.sent_at)}
          </span>
          {message.remote_visibility === 'unknown' && (
            <Badge variant="outline" className="text-xs h-5 px-1.5">
              Pending
            </Badge>
          )}
          {message.remote_visibility === 'deleted_by_author' && (
            <Badge variant="secondary" className="text-xs h-5 px-1.5">
              Deleted
            </Badge>
          )}

          {/* Delete button - only for pending outgoing messages */}
          {canDelete && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-5 w-5 p-0"
                  disabled={isDeleting}
                >
                  {isDeleting ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <MoreVertical className="h-3 w-3" />
                  )}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-40">
                <DropdownMenuItem
                  onClick={() => onDelete(message.id)}
                  className="text-destructive focus:text-destructive"
                >
                  <Trash2 className="h-4 w-4 mr-2" />
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>
    </div>
  );
}

function MessagesSkeleton() {
  return (
    <div className="space-y-4 p-4">
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} className={cn(
          "flex gap-3",
          i % 2 === 0 ? "flex-row-reverse" : "flex-row"
        )}>
          {i % 2 !== 0 && <Skeleton className="h-8 w-8 rounded-full" />}
          <Skeleton className={cn(
            "h-16 rounded-2xl",
            i % 2 === 0 ? "w-48" : "w-64"
          )} />
        </div>
      ))}
    </div>
  );
}

export default function ConversationDetailPage() {
  const params = useParams();
  const router = useRouter();
  const conversationId = params.conversationId as string;

  const [conversation, setConversation] = useState<ConversationDetail | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [messageText, setMessageText] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [deletingMessages, setDeletingMessages] = useState<Set<number>>(new Set());
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [messageToDelete, setMessageToDelete] = useState<number | null>(null);
  const [attachmentIds, setAttachmentIds] = useState<number[]>([]);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  // Fetch a single page of messages with optional cursor for pagination
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

  // Fetch ALL messages by recursively loading all pages
  const fetchAllMessages = useCallback(async (): Promise<{ messages: Message[]; nextCursor: string | null; hasMore: boolean }> => {
    const allMessages: Message[] = [];
    let cursor: string | undefined = undefined;
    let hasMore = true;

    // Keep fetching until we have all messages
    while (hasMore) {
      const page = await fetchMessagesPage(cursor);
      allMessages.push(...page.messages);
      cursor = page.next_cursor || undefined;
      hasMore = page.has_more;

      // Safety limit to prevent infinite loops (max 50 pages = 5000 messages)
      if (allMessages.length > 5000) {
        return {
          messages: allMessages,
          nextCursor: cursor || null,
          hasMore: hasMore
        };
      }
    }

    return {
      messages: allMessages,
      nextCursor: null,
      hasMore: false
    };
  }, [fetchMessagesPage]);

  // Load older messages (used when safety limit was hit)
  const loadOlderMessages = useCallback(async () => {
    if (!nextCursor || loadingOlder) return;

    setLoadingOlder(true);
    try {
      const msgsData = await fetchMessagesPage(nextCursor);
      // Older messages (DESC order) - prepend to beginning after reversing
      const olderMessages = msgsData.messages.reverse();
      setMessages(prev => [...olderMessages, ...prev]);
      setNextCursor(msgsData.next_cursor);
      setHasMore(msgsData.has_more);
    } catch (err) {
      console.error('Failed to load older messages:', err);
    } finally {
      setLoadingOlder(false);
    }
  }, [nextCursor, loadingOlder, fetchMessagesPage]);

  // Send message
  const sendMessage = useCallback(async () => {
    if (!messageText.trim() || sending) return;

    setSending(true);
    setSendError(null);

    try {
      const response = await fetch(
        `/api/core/conversations/${conversationId}/messages`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            body_text: messageText.trim(),
            attachment_ids: attachmentIds.length > 0 ? attachmentIds : undefined,
          }),
        }
      );

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to send message');
      }

      const result = await response.json();

      // Add optimistic message to the list
      const optimisticMessage: Message = {
        id: result.message_id,
        direction: 'out',
        body_text: messageText.trim(),
        sent_at: new Date().toISOString(),
        remote_visibility: 'unknown',
        identity_id: conversation?.identity_id || null,
        created_at: new Date().toISOString(),
      };

      setMessages(prev => [...prev, optimisticMessage]);
      setMessageText('');
      setAttachmentIds([]);
      setTimeout(scrollToBottom, 100);
    } catch (err) {
      setSendError(err instanceof Error ? err.message : 'Failed to send message');
    } finally {
      setSending(false);
    }
  }, [messageText, sending, conversationId, conversation?.identity_id, attachmentIds]);

  // Delete message
  const deleteMessage = useCallback(async (messageId: number) => {
    // Add to deleting set
    setDeletingMessages(prev => {
      const next = new Set(prev);
      next.add(messageId);
      return next;
    });

    setDeleteError(null);

    try {
      const response = await fetch(
        `/api/core/conversations/${conversationId}/messages/${messageId}`,
        {
          method: 'DELETE',
          credentials: 'include',
        }
      );

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to delete message');
      }

      // Optimistically remove message from UI
      setMessages(prev => prev.filter(m => m.id !== messageId));
      setMessageToDelete(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'Failed to delete message');
    } finally {
      // Remove from deleting set
      setDeletingMessages(prev => {
        const next = new Set(prev);
        next.delete(messageId);
        return next;
      });
    }
  }, [conversationId]);

  // Handle attachment file selection
  const handleAttachmentSelect = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0) return;

    setUploadingAttachment(true);

    try {
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch(
          `/api/core/conversations/${conversationId}/attachments`,
          {
            method: 'POST',
            credentials: 'include',
            body: formData,
          }
        );

        if (!response.ok) {
          const data = await response.json();
          setSendError(data.detail || `Failed to upload ${file.name}`);
          continue;
        }

        const data = await response.json();
        setAttachmentIds(prev => [...prev, data.attachment_id]);
      }
    } catch (err) {
      setSendError(err instanceof Error ? err.message : 'Failed to upload attachment');
    } finally {
      setUploadingAttachment(false);
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  }, [conversationId]);

  // Handle Enter key to send
  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }, [sendMessage]);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError(null);

      try {
        // Fetch conversation details first
        const convResponse = await fetch(`/api/core/conversations/${conversationId}`, { credentials: 'include' });

        if (!convResponse.ok) {
          if (convResponse.status === 404) {
            throw new Error('Conversation not found');
          }
          if (convResponse.status === 401) {
            throw new Error('Please log in to view this conversation');
          }
          const data = await convResponse.json();
          throw new Error(data.detail || 'Failed to load conversation');
        }

        const convData: ConversationDetail = await convResponse.json();
        setConversation(convData);

        // Fetch ALL messages (auto-paginate through entire history)
        const msgsData = await fetchAllMessages();

        // Messages come in DESC order, reverse for display (oldest first)
        setMessages(msgsData.messages.reverse());
        setNextCursor(msgsData.nextCursor);
        setHasMore(msgsData.hasMore);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [conversationId, fetchAllMessages]);

  useEffect(() => {
    if (!loading && messages.length > 0) {
      scrollToBottom();
    }
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
              <Button variant="outline" onClick={() => router.push('/inbox')}>
                Back to Inbox
              </Button>
              <Button onClick={() => window.location.reload()}>
                Try Again
              </Button>
            </div>
          </Card>
        </div>
      </div>
    );
  }

  if (!conversation) {
    return null;
  }

  const { counterpart } = conversation;

  return (
    <div className="flex flex-col h-[calc(100vh-10rem)] min-h-[400px] border border-border rounded-lg bg-card overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-4 p-4 border-b border-border shrink-0">
        <Link href="/inbox">
          <Button variant="ghost" size="icon">
            <ArrowLeft className="h-5 w-5" />
          </Button>
        </Link>

        <Avatar className="h-10 w-10">
          <AvatarFallback className="bg-primary/10 text-primary">
            {getInitials(counterpart.external_username)}
          </AvatarFallback>
        </Avatar>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold truncate">
              u/{counterpart.external_username}
            </span>
            {counterpart.remote_status === 'deleted' && (
              <Badge variant="secondary" className="text-xs">Deleted</Badge>
            )}
            {counterpart.remote_status === 'suspended' && (
              <Badge variant="destructive" className="text-xs">Suspended</Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            {conversation.provider_id === 'reddit' ? 'Reddit' : conversation.provider_id}
          </p>
        </div>

        <a
          href={`https://reddit.com/u/${counterpart.external_username}`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-muted-foreground hover:text-foreground transition-colors"
        >
          <ExternalLink className="h-4 w-4" />
        </a>
      </div>

      {/* Messages */}
      <div ref={messagesContainerRef} className="flex-1 overflow-y-auto p-4 min-w-0">
        {/* Load older messages button - only shown when safety limit (5000) was hit */}
        {hasMore && (
          <div className="flex flex-col items-center gap-2 mb-4">
            <p className="text-xs text-muted-foreground">
              {messages.length.toLocaleString()} messages loaded
            </p>
            <Button
              variant="ghost"
              size="sm"
              onClick={loadOlderMessages}
              disabled={loadingOlder}
              className="text-muted-foreground"
            >
              {loadingOlder ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : (
                <ChevronUp className="h-4 w-4 mr-2" />
              )}
              {loadingOlder ? 'Loading...' : 'Load more messages'}
            </Button>
          </div>
        )}

        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-muted-foreground">No messages yet</p>
          </div>
        ) : (
          <>
            {messages.map((msg) => (
              <MessageBubble
                key={msg.id}
                message={msg}
                counterpartUsername={counterpart.external_username}
                onDelete={setMessageToDelete}
                isDeleting={deletingMessages.has(msg.id)}
              />
            ))}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Compose Box */}
      <div className="p-4 border-t border-border shrink-0">
        {sendError && (
          <div className="mb-2 p-2 bg-destructive/10 text-destructive text-sm rounded-md flex items-center gap-2">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{sendError}</span>
            <button
              onClick={() => setSendError(null)}
              className="ml-auto text-xs underline"
            >
              Dismiss
            </button>
          </div>
        )}
        {deleteError && (
          <div className="mb-4 rounded-lg border border-destructive bg-destructive/10 p-3">
            <div className="flex items-start gap-2">
              <AlertCircle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="text-sm font-medium text-destructive">
                  Failed to delete message
                </p>
                <p className="text-sm text-destructive/80 mt-1">
                  {deleteError}
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setDeleteError(null)}
                className="h-6 w-6 p-0"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
        <div className="flex gap-2 max-w-full">
          <Textarea
            value={messageText}
            onChange={(e) => setMessageText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              counterpart.remote_status === 'deleted' || counterpart.remote_status === 'suspended'
                ? `Cannot send to ${counterpart.remote_status} user`
                : 'Type a message... (Enter to send, Shift+Enter for new line)'
            }
            className="min-h-[44px] max-h-32 resize-none flex-1 min-w-0"
            disabled={sending || counterpart.remote_status === 'deleted' || counterpart.remote_status === 'suspended'}
            rows={1}
          />
          <div className="flex gap-1 shrink-0">
            <Button
              size="icon"
              variant="ghost"
              className="h-11 w-11"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadingAttachment || sending}
              title="Attach files"
            >
              {uploadingAttachment ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Paperclip className="h-4 w-4" />
              )}
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="image/*,application/pdf,.doc,.docx,.xls,.xlsx"
              className="hidden"
              onChange={(e) => handleAttachmentSelect(e.target.files)}
              disabled={uploadingAttachment || sending}
            />
            <Button
              size="icon"
              className="shrink-0 h-11 w-11"
              onClick={sendMessage}
              disabled={!messageText.trim() || sending || counterpart.remote_status === 'deleted' || counterpart.remote_status === 'suspended'}
              title={sending ? 'Sending...' : 'Send message'}
            >
              {sending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>

        {/* Show uploaded attachments */}
        {attachmentIds.length > 0 && (
          <div className="mt-2 p-2 bg-muted rounded-md">
            <p className="text-xs font-medium text-muted-foreground mb-1">
              {attachmentIds.length} attachment{attachmentIds.length !== 1 ? 's' : ''} attached
            </p>
            <div className="flex gap-1 flex-wrap">
              {attachmentIds.map((id) => (
                <Badge key={id} variant="secondary" className="text-xs">
                  Attachment #{id}
                  <button
                    onClick={() => setAttachmentIds(prev => prev.filter(aid => aid !== id))}
                    className="ml-1 hover:text-destructive"
                  >
                    ✕
                  </button>
                </Badge>
              ))}
            </div>
          </div>
        )}

        <p className="text-xs text-muted-foreground mt-2 text-center">
          Messages are queued and sent in the background
        </p>
      </div>

      {/* Delete confirmation dialog */}
      <Dialog open={messageToDelete !== null} onOpenChange={(open) => !open && setMessageToDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Message?</DialogTitle>
            <DialogDescription>
              This will permanently delete this pending message. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setMessageToDelete(null)}
              disabled={messageToDelete !== null && deletingMessages.has(messageToDelete)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => messageToDelete && deleteMessage(messageToDelete)}
              disabled={messageToDelete !== null && deletingMessages.has(messageToDelete)}
            >
              {messageToDelete !== null && deletingMessages.has(messageToDelete) ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Deleting...
                </>
              ) : (
                'Delete'
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
