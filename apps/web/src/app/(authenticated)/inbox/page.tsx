'use client';

import { useEffect, useState, useMemo, useCallback, useRef, Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams, useRouter } from 'next/navigation';
import { AlertTriangle, Loader2, MessageSquare, Paperclip, RefreshCw, Reply, Search, Star, X } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components';
import { IdentityFilter, IdentityBadge } from '@/components/identity';
import { useIdentities } from '@/hooks/useIdentities';
import { cn } from '@/lib/utils';

interface Counterpart {
  id: number;
  external_username: string;
  external_user_id: string | null;
  remote_status: string;
  is_starred: boolean;
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
  has_failed_messages: boolean;
  archived_at: string | null;
  created_at: string;
}

interface ConversationsResponse {
  conversations: Conversation[];
  next_cursor: string | null;
  has_more: boolean;
}

interface SearchConversation extends Conversation {
  matching_snippet: string | null;
}

interface SearchResponse {
  conversations: SearchConversation[];
  total: number;
}

function getInitials(username: string): string {
  return username.slice(0, 2).toUpperCase();
}

function formatRelativeTime(dateString: string | null): string {
  if (!dateString) return '';

  // Backend returns naive UTC datetimes (no Z suffix) — ensure JS parses as UTC
  const normalized = dateString.endsWith('Z') || dateString.includes('+') ? dateString : dateString + 'Z';
  const date = new Date(normalized);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  // Include year if not current year
  const isCurrentYear = date.getFullYear() === now.getFullYear();
  if (isCurrentYear) {
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
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

function ConversationItem({
  conversation,
  identity,
  onToggleStar,
  matchingSnippet,
}: {
  conversation: Conversation;
  identity?: { provider_id: string; display_name: string; external_username: string };
  onToggleStar: (accountId: number) => void;
  matchingSnippet?: string | null;
}) {
  const { counterpart, last_message_preview, last_activity_at, unread_count, has_failed_messages } = conversation;

  return (
    <Link href={`/inbox/${conversation.id}`}>
      <div className="flex items-center gap-4 p-4 hover:bg-muted/50 transition-colors cursor-pointer border-b border-border last:border-b-0">
        <div className="relative">
          <Avatar className="h-12 w-12">
            <AvatarFallback className="bg-primary/10 text-primary font-medium">
              {getInitials(counterpart.external_username)}
            </AvatarFallback>
          </Avatar>
          {has_failed_messages && (
            <div className="absolute -top-1 -right-1 h-5 w-5 rounded-full bg-destructive flex items-center justify-center" title="Has failed messages">
              <AlertTriangle className="h-3 w-3 text-destructive-foreground" />
            </div>
          )}
        </div>

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

          {matchingSnippet ? (
            <p className="text-sm text-muted-foreground truncate mt-0.5 flex items-center gap-1.5">
              <Search className="h-3 w-3 shrink-0 text-primary" />
              <span className="truncate">{matchingSnippet}</span>
            </p>
          ) : (
            <p className="text-sm text-muted-foreground truncate mt-0.5">
              {last_message_preview || 'No messages yet'}
            </p>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onToggleStar(counterpart.id);
            }}
            className={cn(
              "p-1 rounded transition-colors",
              counterpart.is_starred
                ? "text-yellow-500 hover:text-yellow-600"
                : "text-muted-foreground/40 hover:text-muted-foreground"
            )}
            title={counterpart.is_starred ? "Unstar" : "Star"}
          >
            <Star className={cn("h-4 w-4", counterpart.is_starred && "fill-current")} />
          </button>
          <div className="flex flex-col items-end gap-1">
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
      </div>
    </Link>
  );
}

function InboxContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Initialize filters from URL params
  const initialAttachments = searchParams.get('attachments') === 'true';
  const initialReplies = searchParams.get('replies') === 'true';

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [totalCount, setTotalCount] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchConversation[] | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [identityFilter, setIdentityFilter] = useState<number | null>(null);
  const [hasAttachmentsFilter, setHasAttachmentsFilter] = useState(initialAttachments);
  const [hasRepliesFilter, setHasRepliesFilter] = useState(initialReplies);

  // Update URL when filters change
  const updateUrlParams = useCallback((attachments: boolean, replies: boolean) => {
    const params = new URLSearchParams();
    if (attachments) params.set('attachments', 'true');
    if (replies) params.set('replies', 'true');
    const queryString = params.toString();
    router.replace(queryString ? `/inbox?${queryString}` : '/inbox', { scroll: false });
  }, [router]);

  const toggleAttachmentsFilter = useCallback(() => {
    const newValue = !hasAttachmentsFilter;
    setHasAttachmentsFilter(newValue);
    updateUrlParams(newValue, hasRepliesFilter);
  }, [hasAttachmentsFilter, hasRepliesFilter, updateUrlParams]);

  const toggleRepliesFilter = useCallback(() => {
    const newValue = !hasRepliesFilter;
    setHasRepliesFilter(newValue);
    updateUrlParams(hasAttachmentsFilter, newValue);
  }, [hasAttachmentsFilter, hasRepliesFilter, updateUrlParams]);

  const clearFilters = useCallback(() => {
    setHasAttachmentsFilter(false);
    setHasRepliesFilter(false);
    updateUrlParams(false, false);
  }, [updateUrlParams]);

  const { identities, loading: identitiesLoading } = useIdentities();

  // Build identity lookup map
  const identityMap = useMemo(() => {
    const map: Record<number, typeof identities[0]> = {};
    identities.forEach(i => { map[i.id] = i; });
    return map;
  }, [identities]);

  // Filter conversations by identity (only for non-search mode)
  const filteredConversations = useMemo(() => {
    if (identityFilter === null) return conversations;
    return conversations.filter(conv => conv.identity_id === identityFilter);
  }, [conversations, identityFilter]);

  // Backend search
  const searchConversations = useCallback(async (query: string) => {
    if (!query.trim()) {
      setSearchResults(null);
      setSearchLoading(false);
      return;
    }

    setSearchLoading(true);
    try {
      const params = new URLSearchParams({ q: query.trim() });
      if (identityFilter !== null) {
        params.set('identity_id', String(identityFilter));
      }
      const response = await fetch(`/api/core/conversations/search?${params.toString()}`, {
        credentials: 'include',
      });
      if (!response.ok) {
        setSearchResults([]);
        return;
      }
      const data: SearchResponse = await response.json();
      setSearchResults(data.conversations);
    } catch {
      setSearchResults([]);
    } finally {
      setSearchLoading(false);
    }
  }, [identityFilter]);

  // Debounced search input handler
  const handleSearchChange = useCallback((value: string) => {
    setSearchQuery(value);
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }
    if (!value.trim()) {
      setSearchResults(null);
      setSearchLoading(false);
      return;
    }
    setSearchLoading(true);
    searchTimeoutRef.current = setTimeout(() => {
      searchConversations(value);
    }, 400);
  }, [searchConversations]);

  // Clear search
  const clearSearch = useCallback(() => {
    setSearchQuery('');
    setSearchResults(null);
    setSearchLoading(false);
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }
  }, []);

  // Re-trigger search when identity filter changes while searching
  useEffect(() => {
    if (searchQuery.trim()) {
      searchConversations(searchQuery);
    }
  }, [identityFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  // Determine which conversations to display
  const isSearching = searchResults !== null;
  const displayConversations = isSearching ? searchResults : filteredConversations;

  const handleToggleStar = useCallback(async (accountId: number) => {
    try {
      const response = await fetch(`/api/core/directories/${accountId}/star`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) {
        console.error('Failed to toggle star');
        return;
      }

      const result = await response.json();

      // Update the counterpart's is_starred in local state
      const updateStar = (conv: Conversation) =>
        conv.counterpart.id === accountId
          ? { ...conv, counterpart: { ...conv.counterpart, is_starred: result.is_starred } }
          : conv;
      setConversations((prev) => prev.map(updateStar));
      setSearchResults((prev) => prev ? prev.map(updateStar) as SearchConversation[] : null);
    } catch (err) {
      console.error('Failed to toggle star:', err);
    }
  }, []);

  const fetchConversations = useCallback(async (isRefresh = false, cursor?: string) => {
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
      if (hasAttachmentsFilter) {
        params.set('has_attachments', 'true');
      }
      if (hasRepliesFilter) {
        params.set('has_replies', 'true');
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
  }, [hasAttachmentsFilter, hasRepliesFilter]);

  const loadMore = useCallback(() => {
    if (nextCursor && !loadingMore) {
      fetchConversations(false, nextCursor);
    }
  }, [fetchConversations, nextCursor, loadingMore]);

  // Refetch when filters change
  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

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

      {/* Message Filters */}
      <div className="flex gap-2 mb-4">
        <Button
          variant={hasAttachmentsFilter ? "default" : "outline"}
          size="sm"
          onClick={toggleAttachmentsFilter}
          className={hasAttachmentsFilter ? "gap-1.5 shadow-sm" : "gap-1.5"}
        >
          <Paperclip className="h-3.5 w-3.5" />
          With Attachments
        </Button>
        <Button
          variant={hasRepliesFilter ? "default" : "outline"}
          size="sm"
          onClick={toggleRepliesFilter}
          className={hasRepliesFilter ? "gap-1.5 shadow-sm" : "gap-1.5"}
        >
          <Reply className="h-3.5 w-3.5" />
          With Replies
        </Button>
      </div>

      {/* Search Field */}
      <div className="relative mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          type="text"
          placeholder="Search all messages..."
          value={searchQuery}
          onChange={(e) => handleSearchChange(e.target.value)}
          className="pl-10 pr-10"
        />
        {searchQuery && (
          <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-1">
            {searchLoading && (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            )}
            <button
              onClick={clearSearch}
              className="text-muted-foreground hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>

      {isSearching && displayConversations.length === 0 && !searchLoading ? (
        <Card className="p-8">
          <div className="text-center">
            <Search className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-muted-foreground">
              No messages matching &quot;{searchQuery}&quot;
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Searched through all messages across all conversations
            </p>
            <Button
              variant="link"
              onClick={clearSearch}
              className="mt-2"
            >
              Clear search
            </Button>
          </div>
        </Card>
      ) : conversations.length === 0 && (hasAttachmentsFilter || hasRepliesFilter) ? (
        <Card className="p-8">
          <div className="text-center">
            {hasAttachmentsFilter && hasRepliesFilter ? (
              <div className="flex justify-center gap-2 mb-4">
                <Paperclip className="h-8 w-8 text-muted-foreground" />
                <Reply className="h-8 w-8 text-muted-foreground" />
              </div>
            ) : hasAttachmentsFilter ? (
              <Paperclip className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
            ) : (
              <Reply className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
            )}
            <p className="text-muted-foreground">
              No conversations {hasAttachmentsFilter && hasRepliesFilter
                ? 'with attachments and replies'
                : hasAttachmentsFilter
                  ? 'with attachments'
                  : 'with replies'}
            </p>
            <Button
              variant="link"
              onClick={clearFilters}
              className="mt-2"
            >
              Clear filters
            </Button>
          </div>
        </Card>
      ) : (
        <>
          <Card className="overflow-hidden">
            {displayConversations.map((conversation) => (
              <ConversationItem
                key={conversation.id}
                conversation={conversation}
                identity={identities.length > 1 ? identityMap[conversation.identity_id] : undefined}
                onToggleStar={handleToggleStar}
                matchingSnippet={isSearching ? (conversation as SearchConversation).matching_snippet : undefined}
              />
            ))}
          </Card>

          {hasMore && !isSearching && (
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
            {isSearching ? (
              <>Found {displayConversations.length} conversation{displayConversations.length !== 1 ? 's' : ''} matching &quot;{searchQuery}&quot;</>
            ) : (
              <>
                Showing {conversations.length} conversation{conversations.length !== 1 ? 's' : ''}
                {(hasAttachmentsFilter || hasRepliesFilter) && (
                  <span className="text-primary">
                    {' '}(filtered{hasAttachmentsFilter && hasRepliesFilter
                      ? ': attachments + replies'
                      : hasAttachmentsFilter
                        ? ': attachments'
                        : ': replies'})
                  </span>
                )}
                {hasMore && ' (more available)'}
              </>
            )}
          </p>
        </>
      )}
    </div>
  );
}

// Loading fallback for Suspense
function InboxLoading() {
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

export default function InboxPage() {
  return (
    <Suspense fallback={<InboxLoading />}>
      <InboxContent />
    </Suspense>
  );
}
