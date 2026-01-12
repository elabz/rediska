'use client';

import { useEffect, useState, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, Loader2, Send, AlertCircle, ExternalLink } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
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

interface Message {
  id: number;
  direction: 'in' | 'out' | 'system';
  body_text: string | null;
  sent_at: string;
  remote_visibility: string;
  identity_id: number | null;
  created_at: string;
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

function MessageBubble({ message, counterpartUsername }: { message: Message; counterpartUsername: string }) {
  const isOutgoing = message.direction === 'out';
  const isSystem = message.direction === 'system';

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
      "flex gap-3 mb-4",
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
  const [error, setError] = useState<string | null>(null);
  const [messageText, setMessageText] = useState('');

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError(null);

      try {
        // Fetch conversation details and messages in parallel
        const [convResponse, msgsResponse] = await Promise.all([
          fetch(`/api/core/conversations/${conversationId}`, { credentials: 'include' }),
          fetch(`/api/core/conversations/${conversationId}/messages?limit=50`, { credentials: 'include' }),
        ]);

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

        if (!msgsResponse.ok) {
          const data = await msgsResponse.json();
          throw new Error(data.detail || 'Failed to load messages');
        }

        const convData: ConversationDetail = await convResponse.json();
        const msgsData: MessagesResponse = await msgsResponse.json();

        setConversation(convData);
        // Messages come in DESC order, reverse for display
        setMessages(msgsData.messages.reverse());
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [conversationId]);

  useEffect(() => {
    if (!loading && messages.length > 0) {
      scrollToBottom();
    }
  }, [loading, messages]);

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
      <div className="flex-1 overflow-y-auto p-4 min-w-0">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-muted-foreground">No messages yet</p>
          </div>
        ) : (
          <>
            {messages.map((message) => (
              <MessageBubble
                key={message.id}
                message={message}
                counterpartUsername={counterpart.external_username}
              />
            ))}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Compose Box */}
      <div className="p-4 border-t border-border shrink-0">
        <div className="flex gap-2 max-w-full">
          <Textarea
            value={messageText}
            onChange={(e) => setMessageText(e.target.value)}
            placeholder="AI-assisted messaging coming soon..."
            className="min-h-[44px] max-h-32 resize-none flex-1 min-w-0"
            disabled
            rows={1}
          />
          <Button
            size="icon"
            className="shrink-0 h-11 w-11"
            disabled
            title="Sending messages will be enabled soon"
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
        <p className="text-xs text-muted-foreground mt-2 text-center">
          AI-assisted message composition coming in the next update
        </p>
      </div>
    </div>
  );
}
