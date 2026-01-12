'use client';

import { useEffect, useState, useMemo, useCallback } from 'react';
import Link from 'next/link';
import { Loader2, MessageSquare, RefreshCw, Search, X } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components';
import { IdentityFilter, IdentityBadge } from '@/components/identity';
import { useIdentities } from '@/hooks/useIdentities';

interface Counterpart {
  id: number;
  external_username: string;
  external_user_id: string | null;
  remote_status: string;
}

interface Conversation {
  id: number;
  provider_id: string;
  identity_id: number;
  external_conversation_id: string;
  counterpart: Counterpart;
  last_activity_at: string | null;
  last_message_preview: string | null;
  unread_count: number;
  archived_at: string | null;
  created_at: string;
}

interface ConversationsResponse {
  conversations: Conversation[];
  next_cursor: string | null;
  has_more: boolean;
}

function getInitials(username: string): string {
  return username.slice(0, 2).toUpperCase();
}

function formatRelativeTime(dateString: string | null): string {
  if (!dateString) return '';

  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function ConversationSkeleton() {
  return (
    <div className="flex items-center gap-4 p-4">
      <Skeleton className="h-12 w-12 rounded-full" />
      <div className="flex-1 space-y-2">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-3 w-48" />
      </div>
      <Skeleton className="h-3 w-12" />
    </div>
  );
}

function ConversationItem({ conversation, identity }: { conversation: Conversation; identity?: { provider_id: string; display_name: string; external_username: string } }) {
  const { counterpart, last_message_preview, last_activity_at, unread_count } = conversation;

  return (
    <Link href={`/inbox/${conversation.id}`}>
      <div className="flex items-center gap-4 p-4 hover:bg-muted/50 transition-colors cursor-pointer border-b border-border last:border-b-0">
        <Avatar className="h-12 w-12">
          <AvatarFallback className="bg-primary/10 text-primary font-medium">
            {getInitials(counterpart.external_username)}
          </AvatarFallback>
        </Avatar>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium truncate">
              u/{counterpart.external_username}
            </span>
            {identity && (
              <IdentityBadge identity={identity} size="sm" />
            )}
            {counterpart.remote_status === 'deleted' && (
              <Badge variant="secondary" className="text-xs">Deleted</Badge>
            )}
            {counterpart.remote_status === 'suspended' && (
              <Badge variant="destructive" className="text-xs">Suspended</Badge>
            )}
          </div>

          <p className="text-sm text-muted-foreground truncate mt-0.5">
            {last_message_preview || 'No messages yet'}
          </p>
        </div>

        <div className="flex flex-col items-end gap-1 shrink-0">
          <span className="text-xs text-muted-foreground">
            {formatRelativeTime(last_activity_at)}
          </span>
          {unread_count > 0 && (
            <Badge className="h-5 min-w-5 justify-center text-xs">
              {unread_count}
            </Badge>
          )}
        </div>
      </div>
    </Link>
  );
}

export default function InboxPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [totalCount, setTotalCount] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [identityFilter, setIdentityFilter] = useState<number | null>(null);

  const { identities, loading: identitiesLoading } = useIdentities();

  // Build identity lookup map
  const identityMap = useMemo(() => {
    const map: Record<number, typeof identities[0]> = {};
    identities.forEach(i => { map[i.id] = i; });
    return map;
  }, [identities]);

  // Filter conversations based on search query and identity
  const filteredConversations = useMemo(() => {
    let filtered = conversations;

    // Filter by identity
    if (identityFilter !== null) {
      filtered = filtered.filter(conv => conv.identity_id === identityFilter);
    }

    // Filter by search query
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter((conv) => {
        // Search in username
        if (conv.counterpart.external_username.toLowerCase().includes(query)) {
          return true;
        }
        // Search in message preview
        if (conv.last_message_preview?.toLowerCase().includes(query)) {
          return true;
        }
        return false;
      });
    }

    return filtered;
  }, [conversations, searchQuery, identityFilter]);

  const fetchConversations = async (isRefresh = false, cursor?: string) => {
    if (cursor) {
      setLoadingMore(true);
    } else if (isRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);

    try {
      const params = new URLSearchParams({ limit: '50' });
      if (cursor) {
        params.set('cursor', cursor);
      }

      const response = await fetch(`/api/core/conversations?${params.toString()}`, {
        credentials: 'include',
      });

      if (!response.ok) {
        if (response.status === 401) {
          throw new Error('Please log in to view conversations');
        }
        const data = await response.json();
        throw new Error(data.detail || 'Failed to load conversations');
      }

      const data: ConversationsResponse = await response.json();

      if (cursor) {
        // Append to existing conversations
        setConversations(prev => [...prev, ...data.conversations]);
      } else {
        // Replace conversations (initial load or refresh)
        setConversations(data.conversations);
      }

      setNextCursor(data.next_cursor);
      setHasMore(data.has_more);
      if (!cursor && data.conversations.length > 0) {
        // Estimate total from first load
        setTotalCount(data.has_more ? data.conversations.length + 1 : data.conversations.length);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
      setLoadingMore(false);
      setRefreshing(false);
    }
  };

  const loadMore = () => {
    if (nextCursor && !loadingMore) {
      fetchConversations(false, nextCursor);
    }
  };

  useEffect(() => {
    fetchConversations();
  }, []);

  if (loading) {
    return (
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">Inbox</h1>
        </div>
        <Card>
          {[1, 2, 3, 4, 5].map((i) => (
            <ConversationSkeleton key={i} />
          ))}
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">Inbox</h1>
        </div>
        <Card className="p-8">
          <div className="text-center">
            <p className="text-destructive mb-4">{error}</p>
            <Button onClick={() => fetchConversations()}>
              Try Again
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  if (conversations.length === 0) {
    return (
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">Inbox</h1>
        </div>

        <EmptyState
          icon="inbox"
          title="No conversations yet"
          description="Go to Ops to sync messages from Reddit, or use Browse/Leads to find people to connect with."
        />
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Inbox</h1>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => fetchConversations(true)}
          disabled={refreshing}
        >
          {refreshing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
        </Button>
      </div>

      {/* Identity Filter */}
      {identities.length > 1 && (
        <div className="mb-4">
          <IdentityFilter
            identities={identities}
            value={identityFilter}
            onChange={setIdentityFilter}
            showAll={true}
          />
        </div>
      )}

      {/* Search Field */}
      <div className="relative mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          type="text"
          placeholder="Search conversations by username or message..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="pl-10 pr-10"
        />
        {searchQuery && (
          <button
            onClick={() => setSearchQuery('')}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {filteredConversations.length === 0 && searchQuery ? (
        <Card className="p-8">
          <div className="text-center">
            <Search className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-muted-foreground">
              No conversations matching &quot;{searchQuery}&quot;
            </p>
            <Button
              variant="link"
              onClick={() => setSearchQuery('')}
              className="mt-2"
            >
              Clear search
            </Button>
          </div>
        </Card>
      ) : (
        <>
          <Card className="overflow-hidden">
            {filteredConversations.map((conversation) => (
              <ConversationItem
                key={conversation.id}
                conversation={conversation}
                identity={identities.length > 1 ? identityMap[conversation.identity_id] : undefined}
              />
            ))}
          </Card>

          {hasMore && !searchQuery && (
            <div className="flex justify-center mt-4">
              <Button
                variant="outline"
                onClick={loadMore}
                disabled={loadingMore}
              >
                {loadingMore ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                    Loading...
                  </>
                ) : (
                  'Load More'
                )}
              </Button>
            </div>
          )}

          <p className="text-sm text-muted-foreground text-center mt-4">
            {searchQuery ? (
              <>Showing {filteredConversations.length} of {conversations.length} conversation{conversations.length !== 1 ? 's' : ''}</>
            ) : (
              <>
                Showing {conversations.length} conversation{conversations.length !== 1 ? 's' : ''}
                {hasMore && ' (more available)'}
              </>
            )}
          </p>
        </>
      )}
    </div>
  );
}
