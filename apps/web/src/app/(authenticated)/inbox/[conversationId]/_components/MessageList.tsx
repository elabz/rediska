'use client';

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react';
import { ChevronUp, Loader2, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { PostsPanel } from '@/components/PostsPanel';
import { cn } from '@/lib/utils';
import type { ConversationDetail, GalleryImage, Message } from '../_types';
import { normalizeUtc } from '../_utils/timeFormat';
import { buildPhrasePattern, extractPhrase } from '../_utils/searchTokens';
import { MessageBubble } from './MessageBubble';
import { ImageGallery } from './ImageGallery';
import { SearchBox } from './SearchBox';

export interface MessageListHandle {
  scrollToBottom: () => void;
  scrollToMessage: (id: number) => boolean;
  scrollToMatch: (index: number) => boolean;
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
  jumpFailed?: boolean;
  onDismissJumpFailed?: () => void;
  initialQuery?: string | null;
  initialJumpMessageId?: number | null;
}

interface MatchPosition {
  messageId: number;
  occurrenceIndex: number;
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
    jumpFailed,
    onDismissJumpFailed,
    initialQuery,
    initialJumpMessageId,
  },
  ref
) {
  const [searchQuery, setSearchQuery] = useState<string>(() => initialQuery ?? '');
  const [galleryExpanded, setGalleryExpanded] = useState(false);
  const [highlightedId, setHighlightedId] = useState<number | null>(null);
  // If the user landed via `?m=<id>&q=<query>`, pre-seed the active match to the
  // deep-linked message so the stronger emphasis lands on the same bubble the
  // orchestrator scrolls to. If that message has no matches once `matches`
  // populates, the re-align effect will fall back to the first overall.
  const [activeMatch, setActiveMatch] = useState<MatchPosition | null>(() =>
    initialQuery && initialJumpMessageId != null
      ? { messageId: initialJumpMessageId, occurrenceIndex: 0 }
      : null
  );
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const messageRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const highlightTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hadMatchesRef = useRef(false);

  const matches = useMemo<MatchPosition[]>(() => {
    const phrase = extractPhrase(searchQuery);
    const pattern = buildPhrasePattern(phrase);
    if (!pattern) return [];
    const out: MatchPosition[] = [];
    for (const msg of messages) {
      const text = msg.body_text;
      if (!text) continue;
      pattern.lastIndex = 0;
      let m: RegExpExecArray | null;
      let occ = 0;
      while ((m = pattern.exec(text)) !== null) {
        out.push({ messageId: msg.id, occurrenceIndex: occ });
        occ++;
        // Guard against zero-length matches.
        if (m.index === pattern.lastIndex) pattern.lastIndex++;
      }
    }
    return out;
  }, [messages, searchQuery]);

  const currentMatchIndex = useMemo<number | null>(() => {
    if (matches.length === 0) return null;
    if (activeMatch) {
      const idx = matches.findIndex(
        (m) => m.messageId === activeMatch.messageId && m.occurrenceIndex === activeMatch.occurrenceIndex
      );
      if (idx >= 0) return idx;
    }
    return 0;
  }, [matches, activeMatch]);

  const scrollToMatchByIndex = useCallback(
    (idx: number): boolean => {
      if (idx < 0 || idx >= matches.length) return false;
      const m = matches[idx];
      const el = messageRefs.current.get(m.messageId);
      if (!el) {
        // Still update the active match so the counter is correct
        setActiveMatch({ messageId: m.messageId, occurrenceIndex: m.occurrenceIndex });
        return false;
      }
      requestAnimationFrame(() => {
        el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      });
      setActiveMatch({ messageId: m.messageId, occurrenceIndex: m.occurrenceIndex });
      return true;
    },
    [matches]
  );

  // Re-align the active match (and auto-scroll on the empty → non-empty transition)
  // whenever the matches array recomputes.
  useEffect(() => {
    if (matches.length === 0) {
      if (activeMatch !== null) setActiveMatch(null);
      hadMatchesRef.current = false;
      return;
    }
    const stillPresent =
      activeMatch &&
      matches.some(
        (m) => m.messageId === activeMatch.messageId && m.occurrenceIndex === activeMatch.occurrenceIndex
      );
    if (stillPresent) {
      hadMatchesRef.current = true;
      return;
    }
    // Active match is gone or never set.
    if (!hadMatchesRef.current) {
      // Empty → non-empty: snap to first match AND scroll.
      scrollToMatchByIndex(0);
    } else {
      // Re-align silently after a poll-induced shift.
      setActiveMatch({ messageId: matches[0].messageId, occurrenceIndex: matches[0].occurrenceIndex });
    }
    hadMatchesRef.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matches]);

  useImperativeHandle(
    ref,
    () => ({
      scrollToBottom: () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
      },
      scrollToMessage: (id: number) => {
        const el = messageRefs.current.get(id);
        if (!el) return false;
        requestAnimationFrame(() => {
          el.scrollIntoView({ block: 'center', behavior: 'smooth' });
        });
        setHighlightedId(id);
        if (highlightTimeoutRef.current) clearTimeout(highlightTimeoutRef.current);
        highlightTimeoutRef.current = setTimeout(() => setHighlightedId(null), 1500);
        return true;
      },
      scrollToMatch: (index: number) => scrollToMatchByIndex(index),
    }),
    [scrollToMatchByIndex]
  );

  // Auto-clear the jump-failed notice when the user changes the search query.
  useEffect(() => {
    if (jumpFailed && searchQuery) {
      onDismissJumpFailed?.();
    }
    // Intentionally omit jumpFailed/onDismissJumpFailed to only react to searchQuery changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery]);

  useEffect(
    () => () => {
      if (highlightTimeoutRef.current) clearTimeout(highlightTimeoutRef.current);
    },
    []
  );

  const handleLoadOlder = () => {
    if (jumpFailed) onDismissJumpFailed?.();
    onLoadOlder();
  };

  const handlePrev = () => {
    if (matches.length === 0 || currentMatchIndex == null) return;
    const newIdx = (currentMatchIndex - 1 + matches.length) % matches.length;
    scrollToMatchByIndex(newIdx);
  };

  const handleNext = () => {
    if (matches.length === 0 || currentMatchIndex == null) return;
    const newIdx = (currentMatchIndex + 1) % matches.length;
    scrollToMatchByIndex(newIdx);
  };

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
    return images.sort(
      (a, b) =>
        new Date(normalizeUtc(b.sentAt)).getTime() - new Date(normalizeUtc(a.sentAt)).getTime()
    );
  }, [messages]);

  const counterpart = conversation.counterpart;

  const activeOccurrenceByMessageId =
    currentMatchIndex != null && matches[currentMatchIndex]
      ? {
          messageId: matches[currentMatchIndex].messageId,
          occurrenceIndex: matches[currentMatchIndex].occurrenceIndex,
        }
      : null;

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
          currentMatch={currentMatchIndex == null ? 0 : currentMatchIndex + 1}
          totalMatches={matches.length}
          onPrev={handlePrev}
          onNext={handleNext}
        />
      </div>

      <div className="p-4 flex-1">
        {jumpFailed && (
          <div className="mb-4 flex items-start gap-3 rounded-md border border-border bg-muted/50 px-3 py-2 text-sm">
            <p className="flex-1 text-muted-foreground">
              Could not jump to the matching message &mdash; it may be older than the loaded
              range. Use <strong>Load more messages</strong> to fetch earlier history.
            </p>
            <button
              type="button"
              onClick={() => onDismissJumpFailed?.()}
              className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="Dismiss"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {hasMore && !searchQuery && (
          <div className="flex flex-col items-center gap-2 mb-4">
            <p className="text-xs text-muted-foreground">
              {messages.length.toLocaleString()} messages loaded
            </p>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleLoadOlder}
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
            {messages.map((msg) => {
              const activeOccurrenceInBubble =
                activeOccurrenceByMessageId && activeOccurrenceByMessageId.messageId === msg.id
                  ? activeOccurrenceByMessageId.occurrenceIndex
                  : null;
              return (
                <div
                  key={msg.id}
                  ref={(el) => {
                    if (el) messageRefs.current.set(msg.id, el);
                    else messageRefs.current.delete(msg.id);
                  }}
                  className={cn(
                    'rounded-md transition-colors duration-1000',
                    msg.id === highlightedId && 'bg-primary/15'
                  )}
                >
                  <MessageBubble
                    message={msg}
                    counterpartUsername={counterpart.external_username}
                    redditComposeUrl={redditComposeUrl}
                    onDelete={onDeleteMessage}
                    onRetry={onRetryMessage}
                    onRemoteDelete={onRemoteDeleteMessage}
                    isDeleting={deletingMessages.has(msg.id)}
                    isRetrying={retryingMessages.has(msg.id)}
                    isRemoteDeleting={remoteDeletingMessages.has(msg.id)}
                    highlightQuery={searchQuery}
                    activeOccurrenceInBubble={activeOccurrenceInBubble}
                  />
                </div>
              );
            })}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>
    </div>
  );
});
