'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  ChevronDown,
  ChevronUp,
  FileText,
  Loader2,
} from 'lucide-react';

interface ProfileItem {
  id: number;
  item_type: string;
  external_item_id: string;
  item_created_at: string | null;
  text_content: string | null;
  subreddit: string | null;
  link_title: string | null;
  link_id: string | null;
  remote_visibility: string;
}

interface PostsPanelProps {
  accountId: number;
  className?: string;
}

function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffHours < 1) return 'Just now';
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
  if (diffDays < 365) return `${Math.floor(diffDays / 30)}mo ago`;
  return `${Math.floor(diffDays / 365)}y ago`;
}

export function PostsPanel({ accountId, className }: PostsPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [posts, setPosts] = useState<ProfileItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [fetched, setFetched] = useState(false);

  const fetchPosts = useCallback(async () => {
    if (fetched) return;
    setLoading(true);
    try {
      const response = await fetch(
        `/api/core/accounts/${accountId}/profile-items?item_type=post&limit=20`,
        { credentials: 'include' }
      );
      if (response.ok) {
        const data = await response.json();
        setPosts(data.items || []);
        setTotal(data.total || 0);
      }
    } catch (err) {
      console.error('Failed to fetch posts:', err);
    } finally {
      setLoading(false);
      setFetched(true);
    }
  }, [accountId, fetched]);

  useEffect(() => {
    if (expanded && !fetched) {
      fetchPosts();
    }
  }, [expanded, fetched, fetchPosts]);

  return (
    <div className={className}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-2 flex items-center justify-between hover:bg-muted/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">
            Posts{total > 0 ? ` (${total})` : ''}
          </span>
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        )}
      </button>
      {expanded && (
        <div className="px-4 pb-3 max-h-64 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          ) : posts.length === 0 ? (
            <p className="text-xs text-muted-foreground py-3 text-center">
              No posts saved for this user
            </p>
          ) : (
            <div className="divide-y divide-border">
              {posts.map((post) => (
                <div key={post.id} className="py-2 first:pt-0 last:pb-0">
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-0.5">
                    {post.subreddit && (
                      <span>r/{post.subreddit}</span>
                    )}
                    {post.item_created_at && (
                      <>
                        {post.subreddit && <span className="text-muted-foreground/50">·</span>}
                        <span>{formatRelativeTime(post.item_created_at)}</span>
                      </>
                    )}
                  </div>
                  {post.link_title && (
                    <p className="text-xs font-medium mb-0.5 line-clamp-1">{post.link_title}</p>
                  )}
                  <p className="text-xs text-muted-foreground line-clamp-2">
                    {post.text_content || '(No content)'}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
