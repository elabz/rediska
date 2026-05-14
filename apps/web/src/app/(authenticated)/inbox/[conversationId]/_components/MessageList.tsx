'use client';

import { forwardRef, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { ChevronUp, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { PostsPanel } from '@/components/PostsPanel';
import type { ConversationDetail, GalleryImage, Message } from '../_types';
import { normalizeUtc } from '../_utils/timeFormat';
import { MessageBubble } from './MessageBubble';
import { ImageGallery } from './ImageGallery';
import { SearchBox } from './SearchBox';

export interface MessageListHandle {
  scrollToBottom: () => void;
}

interface MessageListProps {
  messages: Message[];
  conversation: ConversationDetail;
  redditComposeUrl: string;
  hasMore: boolean;
  loadingOlder: boolean;
  onLoadOlder: () => void;
  onDeleteMessage: (messageId: number) => void;
  onRetryMessage: (messageId: number) => void;
  onRemoteDeleteMessage: (messageId: number) => void;
  deletingMessages: Set<number>;
  retryingMessages: Set<number>;
  remoteDeletingMessages: Set<number>;
}

export const MessageList = forwardRef<MessageListHandle, MessageListProps>(function MessageList(
  {
    messages,
    conversation,
    redditComposeUrl,
    hasMore,
    loadingOlder,
    onLoadOlder,
    onDeleteMessage,
    onRetryMessage,
    onRemoteDeleteMessage,
    deletingMessages,
    retryingMessages,
    remoteDeletingMessages,
  },
  ref
) {
  const [searchQuery, setSearchQuery] = useState('');
  const [galleryExpanded, setGalleryExpanded] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);

  useImperativeHandle(ref, () => ({
    scrollToBottom: () => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    },
  }), []);

  const filteredMessages = useMemo(() => {
    if (!searchQuery.trim()) return messages;
    const query = searchQuery.toLowerCase();
    return messages.filter(msg => msg.body_text?.toLowerCase().includes(query));
  }, [messages, searchQuery]);

  const allImageAttachments = useMemo(() => {
    const images: GalleryImage[] = [];
    for (const msg of messages) {
      for (const att of msg.attachments || []) {
        if (att.mime_type.startsWith('image/')) {
          images.push({
            attachment: att,
            messageId: msg.id,
            sentAt: msg.sent_at,
          });
        }
      }
    }
    return images.sort((a, b) =>
      new Date(normalizeUtc(b.sentAt)).getTime() - new Date(normalizeUtc(a.sentAt)).getTime()
    );
  }, [messages]);

  const counterpart = conversation.counterpart;

  return (
    <div ref={messagesContainerRef} className="flex-1 overflow-y-auto min-w-0 flex flex-col">
      <div className="sticky top-0 z-10 bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80 border-b border-border">
        <ImageGallery
          images={allImageAttachments}
          expanded={galleryExpanded}
          onToggle={() => setGalleryExpanded(!galleryExpanded)}
        />

        <div className="border-b border-border">
          <PostsPanel accountId={counterpart.id} />
        </div>

        <SearchBox
          value={searchQuery}
          onChange={setSearchQuery}
          filteredCount={filteredMessages.length}
          totalCount={messages.length}
        />
      </div>

      <div className="p-4 flex-1">
        {hasMore && !searchQuery && (
          <div className="flex flex-col items-center gap-2 mb-4">
            <p className="text-xs text-muted-foreground">
              {messages.length.toLocaleString()} messages loaded
            </p>
            <Button
              variant="ghost"
              size="sm"
              onClick={onLoadOlder}
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
        ) : filteredMessages.length === 0 ? (
          <div className="flex items-center justify-center h-32">
            <p className="text-muted-foreground">No messages match your search</p>
          </div>
        ) : (
          <>
            {filteredMessages.map((msg) => (
              <MessageBubble
                key={msg.id}
                message={msg}
                counterpartUsername={counterpart.external_username}
                redditComposeUrl={redditComposeUrl}
                onDelete={onDeleteMessage}
                onRetry={onRetryMessage}
                onRemoteDelete={onRemoteDeleteMessage}
                isDeleting={deletingMessages.has(msg.id)}
                isRetrying={retryingMessages.has(msg.id)}
                isRemoteDeleting={remoteDeletingMessages.has(msg.id)}
              />
            ))}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>
    </div>
  );
});
