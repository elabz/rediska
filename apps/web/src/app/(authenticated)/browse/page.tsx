'use client';

import { useState, useCallback, useEffect, useMemo } from 'react';
import { Loader2, Search, BookmarkPlus, BookmarkCheck, ExternalLink, MessageSquare, ArrowUp, Clock, ChevronDown, Star, StarOff, X, Filter, User } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { EmptyState } from '@/components';

interface BrowsePost {
  provider_id: string;
  source_location: string;
  external_post_id: string;
  title: string;
  body_text: string;
  author_username: string;
  author_external_id: string | null;
  post_url: string;
  post_created_at: string | null;
  score: number;
  num_comments: number;
}

interface BrowseResponse {
  posts: BrowsePost[];
  cursor: string | null;
  source_location: string;
  provider_id: string;
}

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffHours < 1) return 'Just now';
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  // Include year if not current year
  const isCurrentYear = date.getFullYear() === now.getFullYear();
  if (isCurrentYear) {
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function PostCard({
  post,
  onSave,
  isSaving,
  isSaved
}: {
  post: BrowsePost;
  onSave: () => void;
  isSaving: boolean;
  isSaved: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const hasLongContent = post.body_text && post.body_text.length > 300;
  const displayText = isExpanded || !hasLongContent
    ? post.body_text
    : post.body_text.slice(0, 300) + '...';

  return (
    <Card className="p-4 hover:bg-muted/30 transition-colors">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex-1 min-w-0">
          <h3 className="font-medium text-sm leading-tight line-clamp-2">
            {post.title || '(No title)'}
          </h3>
          <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
            <a
              href={`https://reddit.com/u/${post.author_username}`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 hover:text-primary hover:underline"
            >
              <User className="h-3 w-3" />
              u/{post.author_username}
            </a>
            <span>•</span>
            <Badge variant="secondary" className="text-xs h-5 px-1.5">
              r/{post.source_location}
            </Badge>
            {post.post_created_at && (
              <>
                <span>•</span>
                <span>{formatDate(post.post_created_at)}</span>
              </>
            )}
          </div>
        </div>
        <Button
          variant={isSaved ? "secondary" : "outline"}
          size="sm"
          onClick={onSave}
          disabled={isSaving || isSaved}
          className="shrink-0"
        >
          {isSaving ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : isSaved ? (
            <>
              <BookmarkCheck className="h-4 w-4 mr-1" />
              Saved
            </>
          ) : (
            <>
              <BookmarkPlus className="h-4 w-4 mr-1" />
              Save Lead
            </>
          )}
        </Button>
      </div>

      {/* Body */}
      {post.body_text && (
        <div className="mb-3">
          <p className="text-sm text-muted-foreground whitespace-pre-wrap break-words">
            {displayText}
          </p>
          {hasLongContent && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsExpanded(!isExpanded)}
              className="mt-1 h-6 px-2 text-xs"
            >
              {isExpanded ? 'Show less' : 'Show more'}
              <ChevronDown className={`h-3 w-3 ml-1 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
            </Button>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <ArrowUp className="h-3 w-3" />
          {post.score.toLocaleString()}
        </span>
        <span className="flex items-center gap-1">
          <MessageSquare className="h-3 w-3" />
          {post.num_comments.toLocaleString()}
        </span>
        {post.post_url && (
          <a
            href={post.post_url.startsWith('http') ? post.post_url : `https://reddit.com${post.post_url}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-primary hover:underline ml-auto"
          >
            <ExternalLink className="h-3 w-3" />
            View on Reddit
          </a>
        )}
      </div>
    </Card>
  );
}

export default function BrowsePage() {
  const [location, setLocation] = useState('');
  const [posts, setPosts] = useState<BrowsePost[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [savedPosts, setSavedPosts] = useState<Set<string>>(new Set());
  const [savingPosts, setSavingPosts] = useState<Set<string>>(new Set());
  const [recentLocations, setRecentLocations] = useState<string[]>([]);
  const [bookmarkedLocations, setBookmarkedLocations] = useState<string[]>([]);
  const [filterQuery, setFilterQuery] = useState('');
  const [currentLocation, setCurrentLocation] = useState('');

  // Load recent locations and bookmarks from localStorage
  useEffect(() => {
    const storedRecent = localStorage.getItem('rediska_recent_locations');
    if (storedRecent) {
      try {
        setRecentLocations(JSON.parse(storedRecent));
      } catch {
        // Ignore parse errors
      }
    }
    const storedBookmarks = localStorage.getItem('rediska_bookmarked_locations');
    if (storedBookmarks) {
      try {
        setBookmarkedLocations(JSON.parse(storedBookmarks));
      } catch {
        // Ignore parse errors
      }
    }
  }, []);

  // Save location to recent
  const addToRecent = useCallback((loc: string) => {
    setRecentLocations(prev => {
      const updated = [loc, ...prev.filter(l => l.toLowerCase() !== loc.toLowerCase())].slice(0, 10);
      localStorage.setItem('rediska_recent_locations', JSON.stringify(updated));
      return updated;
    });
  }, []);

  // Toggle bookmark
  const toggleBookmark = useCallback((loc: string) => {
    setBookmarkedLocations(prev => {
      const isBookmarked = prev.some(l => l.toLowerCase() === loc.toLowerCase());
      const updated = isBookmarked
        ? prev.filter(l => l.toLowerCase() !== loc.toLowerCase())
        : [...prev, loc];
      localStorage.setItem('rediska_bookmarked_locations', JSON.stringify(updated));
      return updated;
    });
  }, []);

  const isBookmarked = useCallback((loc: string) => {
    return bookmarkedLocations.some(l => l.toLowerCase() === loc.toLowerCase());
  }, [bookmarkedLocations]);

  // Filter posts based on search query
  const filteredPosts = useMemo(() => {
    if (!filterQuery.trim()) return posts;
    const query = filterQuery.toLowerCase();
    return posts.filter(post =>
      post.title.toLowerCase().includes(query) ||
      post.body_text?.toLowerCase().includes(query) ||
      post.author_username.toLowerCase().includes(query)
    );
  }, [posts, filterQuery]);

  // Fetch posts from location - DEFAULT TO NEW (most recent)
  const fetchPosts = useCallback(async (loc: string, nextCursor?: string) => {
    if (!loc.trim()) return;

    const isLoadMore = !!nextCursor;
    if (isLoadMore) {
      setLoadingMore(true);
    } else {
      setLoading(true);
      setPosts([]);
      setCursor(null);
      setFilterQuery('');
    }
    setError(null);
    setHasSearched(true);

    try {
      // Default to 'new' sort for most recent posts
      const params = new URLSearchParams({ limit: '25', sort: 'new' });
      if (nextCursor) params.set('cursor', nextCursor);

      const cleanLocation = loc.replace(/^r\//, '');
      const response = await fetch(
        `/api/core/sources/reddit/locations/${encodeURIComponent(cleanLocation)}/posts?${params.toString()}`,
        { credentials: 'include' }
      );

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail?.error || data.detail || 'Failed to fetch posts');
      }

      const data: BrowseResponse = await response.json();

      if (isLoadMore) {
        setPosts(prev => [...prev, ...data.posts]);
      } else {
        setPosts(data.posts);
        setCurrentLocation(cleanLocation);
        addToRecent(cleanLocation);
      }
      setCursor(data.cursor);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [addToRecent]);

  // Save post as lead (includes author and full article text)
  // Automatically triggers analysis in the background after saving
  const saveAsLead = useCallback(async (post: BrowsePost) => {
    const postKey = `${post.provider_id}:${post.external_post_id}`;

    setSavingPosts(prev => {
      const next = new Set(prev);
      next.add(postKey);
      return next;
    });

    try {
      const response = await fetch('/api/core/leads', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_id: post.provider_id,
          source_location: post.source_location,
          external_post_id: post.external_post_id,
          post_url: post.post_url.startsWith('http') ? post.post_url : `https://reddit.com${post.post_url}`,
          title: post.title,
          body_text: post.body_text, // Save full article text
          author_username: post.author_username,
          author_external_id: post.author_external_id,
          post_created_at: post.post_created_at,
        }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to save lead');
      }

      const savedLead = await response.json();

      setSavedPosts(prev => {
        const next = new Set(prev);
        next.add(postKey);
        return next;
      });

      // Auto-queue analysis in background (don't await - fire and forget)
      // This runs asynchronously so saving feels instant
      if (savedLead.id && savedLead.author_account_id) {
        fetch(`/api/core/leads/${savedLead.id}/analyze`, {
          method: 'POST',
          credentials: 'include',
        }).catch(err => {
          // Log but don't fail the save - analysis can be retried manually
          console.log('Background analysis started for lead', savedLead.id);
        });
      }
    } catch (err) {
      console.error('Failed to save lead:', err);
      // Could show a toast here
    } finally {
      setSavingPosts(prev => {
        const next = new Set(prev);
        next.delete(postKey);
        return next;
      });
    }
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchPosts(location);
  };

  const loadMore = () => {
    if (cursor && !loadingMore) {
      fetchPosts(location, cursor);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Browse</h1>
        <p className="text-muted-foreground mt-1">
          Browse subreddits to find and save potential leads
        </p>
      </div>

      {/* Search Form */}
      <form onSubmit={handleSubmit}>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
              r/
            </span>
            <Input
              type="text"
              placeholder="programming, webdev, startups..."
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              className="pl-8 h-11"
              autoFocus
            />
          </div>
          <Button type="submit" disabled={loading || !location.trim()} className="h-11 px-6">
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <>
                <Search className="h-4 w-4 mr-2" />
                Browse
              </>
            )}
          </Button>
        </div>
      </form>

      {/* Bookmarked Subreddits */}
      {bookmarkedLocations.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <span className="text-sm text-muted-foreground flex items-center">
            <Star className="h-3 w-3 mr-1 fill-yellow-400 text-yellow-400" />
            Bookmarks:
          </span>
          {bookmarkedLocations.map((loc) => (
            <Button
              key={loc}
              variant="outline"
              size="sm"
              onClick={() => {
                setLocation(loc);
                fetchPosts(loc);
              }}
              className="h-7 text-xs group"
            >
              r/{loc}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  toggleBookmark(loc);
                }}
                className="ml-1 opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <X className="h-3 w-3" />
              </button>
            </Button>
          ))}
        </div>
      )}

      {/* Recent Locations */}
      {recentLocations.length > 0 && !hasSearched && (
        <div className="flex flex-wrap gap-2">
          <span className="text-sm text-muted-foreground flex items-center">
            <Clock className="h-3 w-3 mr-1" />
            Recent:
          </span>
          {recentLocations.slice(0, 5).map((loc) => (
            <Button
              key={loc}
              variant="outline"
              size="sm"
              onClick={() => {
                setLocation(loc);
                fetchPosts(loc);
              }}
              className="h-7 text-xs"
            >
              r/{loc}
            </Button>
          ))}
        </div>
      )}

      {/* Error */}
      {error && (
        <Card className="p-6 border-destructive/50 bg-destructive/5">
          <p className="text-destructive text-center">{error}</p>
        </Card>
      )}

      {/* Initial State */}
      {!hasSearched && !error && (
        <EmptyState
          icon="🔍"
          title="Browse subreddits"
          description="Enter a subreddit name to browse posts. Save interesting posts as leads for follow-up."
        />
      )}

      {/* Results */}
      {hasSearched && !loading && !error && (
        <>
          {posts.length === 0 ? (
            <EmptyState
              icon="📭"
              title="No posts found"
              description={`No posts found in r/${location}. Try a different subreddit.`}
            />
          ) : (
            <>
              {/* Results header with bookmark and filter */}
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-2">
                  <p className="text-sm text-muted-foreground">
                    {filterQuery ? `${filteredPosts.length} of ` : ''}{posts.length} post{posts.length !== 1 ? 's' : ''} from r/{currentLocation}
                  </p>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => toggleBookmark(currentLocation)}
                    className="h-7 px-2"
                    title={isBookmarked(currentLocation) ? 'Remove bookmark' : 'Bookmark this subreddit'}
                  >
                    {isBookmarked(currentLocation) ? (
                      <Star className="h-4 w-4 fill-yellow-400 text-yellow-400" />
                    ) : (
                      <StarOff className="h-4 w-4" />
                    )}
                  </Button>
                </div>

                {/* Filter input */}
                <div className="relative w-64">
                  <Filter className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    type="text"
                    placeholder="Filter posts..."
                    value={filterQuery}
                    onChange={(e) => setFilterQuery(e.target.value)}
                    className="pl-9 h-8 text-sm"
                  />
                  {filterQuery && (
                    <button
                      onClick={() => setFilterQuery('')}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>

              {filteredPosts.length === 0 && filterQuery ? (
                <Card className="p-8">
                  <div className="text-center">
                    <Filter className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
                    <p className="text-muted-foreground">
                      No posts matching "{filterQuery}"
                    </p>
                    <Button
                      variant="link"
                      onClick={() => setFilterQuery('')}
                      className="mt-2"
                    >
                      Clear filter
                    </Button>
                  </div>
                </Card>
              ) : (
                <>
                  <div className="space-y-3">
                    {filteredPosts.map((post) => {
                      const postKey = `${post.provider_id}:${post.external_post_id}`;
                      return (
                        <PostCard
                          key={postKey}
                          post={post}
                          onSave={() => saveAsLead(post)}
                          isSaving={savingPosts.has(postKey)}
                          isSaved={savedPosts.has(postKey)}
                        />
                      );
                    })}
                  </div>

                  {cursor && !filterQuery && (
                    <div className="flex justify-center">
                      <Button variant="outline" onClick={loadMore} disabled={loadingMore}>
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
                </>
              )}
            </>
          )}
        </>
      )}

      {loading && hasSearched && (
        <div className="flex items-center justify-center h-32">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      )}
    </div>
  );
}
