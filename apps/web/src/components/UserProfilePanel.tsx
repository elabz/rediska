'use client';

import { useState, useCallback, useEffect } from 'react';
import Link from 'next/link';
import {
  Loader2,
  Sparkles,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  User,
  FileText,
  MessageCircle,
  ImageIcon,
  AlertTriangle,
  ExternalLink,
  Clock,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';

interface ProfileSnapshot {
  id: number;
  fetched_at: string;
  summary_text: string | null;
  signals_json: Record<string, unknown> | null;
  risk_flags_json: Record<string, unknown> | null;
  model_info_json: Record<string, unknown> | null;
  created_at: string;
}

interface AccountDetail {
  id: number;
  provider_id: string;
  external_username: string;
  external_user_id: string | null;
  remote_status: string;
  analysis_state: string;
  contact_state: string;
  engagement_state: string;
  first_analyzed_at: string | null;
  created_at: string;
  updated_at: string;
  latest_snapshot: ProfileSnapshot | null;
}

interface ProfileItem {
  id: number;
  item_type: string;
  external_item_id: string;
  item_created_at: string | null;
  text_content: string | null;
  attachment_id: number | null;
  subreddit: string | null;
  link_title: string | null;
  link_id: string | null;
  remote_visibility: string;
  created_at: string;
}

interface ProfileItemsResponse {
  items: ProfileItem[];
  total: number;
  item_type: string | null;
}

interface UserProfilePanelProps {
  username: string;
  providerId?: string;
  accountId?: number;
  defaultExpanded?: boolean;
  compact?: boolean;
  onAnalysisComplete?: () => void;
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

function SignalsBadges({ signals }: { signals: Record<string, unknown> | null }) {
  if (!signals) return null;

  const badges: { key: string; value: string }[] = [];

  // Extract key signals from the JSON
  if (signals.interests && Array.isArray(signals.interests)) {
    signals.interests.slice(0, 5).forEach((interest: string) => {
      badges.push({ key: 'interest', value: interest });
    });
  }
  if (signals.location && typeof signals.location === 'string') {
    badges.push({ key: 'location', value: signals.location });
  }
  if (signals.age_range && typeof signals.age_range === 'string') {
    badges.push({ key: 'age', value: signals.age_range });
  }
  if (signals.relationship_status && typeof signals.relationship_status === 'string') {
    badges.push({ key: 'relationship', value: signals.relationship_status });
  }

  if (badges.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {badges.map((badge, idx) => (
        <Badge
          key={`${badge.key}-${idx}`}
          variant="secondary"
          className="text-xs"
        >
          {badge.key === 'location' && '📍 '}
          {badge.key === 'age' && '🎂 '}
          {badge.key === 'relationship' && '💑 '}
          {badge.value}
        </Badge>
      ))}
    </div>
  );
}

function RiskFlagsBadges({ riskFlags }: { riskFlags: Record<string, unknown> | null }) {
  if (!riskFlags) return null;

  const flags: string[] = [];

  if (riskFlags.flags && Array.isArray(riskFlags.flags)) {
    flags.push(...(riskFlags.flags as string[]));
  }
  if (riskFlags.concerns && Array.isArray(riskFlags.concerns)) {
    flags.push(...(riskFlags.concerns as string[]));
  }

  if (flags.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0" />
      {flags.slice(0, 3).map((flag, idx) => (
        <Badge
          key={idx}
          variant="outline"
          className="text-xs text-amber-600 border-amber-500/30"
        >
          {flag}
        </Badge>
      ))}
      {flags.length > 3 && (
        <Badge variant="outline" className="text-xs">
          +{flags.length - 3} more
        </Badge>
      )}
    </div>
  );
}

function ImageLightbox({
  src,
  onClose,
}: {
  src: string;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center"
      onClick={onClose}
    >
      <button
        className="absolute top-4 right-4 text-white hover:text-gray-300 text-2xl font-bold z-50"
        onClick={onClose}
      >
        ✕
      </button>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt="Full size"
        className="max-w-[90vw] max-h-[90vh] object-contain"
        onClick={(e) => e.stopPropagation()}
      />
    </div>
  );
}

function ProfileItemsList({
  items,
  itemType,
  loading,
}: {
  items: ProfileItem[];
  itemType: 'post' | 'comment' | 'image';
  loading: boolean;
}) {
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="py-6 text-center text-sm text-muted-foreground">
        No {itemType}s found
      </div>
    );
  }

  if (itemType === 'image') {
    return (
      <>
        {lightboxSrc && (
          <ImageLightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} />
        )}
        <div className="grid grid-cols-4 gap-2 py-2">
          {items.map((item) => (
            <div key={item.id} className="aspect-square bg-muted rounded overflow-hidden">
              {item.attachment_id ? (
                <button
                  className="w-full h-full"
                  onClick={() => setLightboxSrc(`/api/core/attachments/${item.attachment_id}`)}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`/api/core/attachments/${item.attachment_id}`}
                    alt="Profile image"
                    className="w-full h-full object-cover hover:opacity-80 transition-opacity cursor-pointer"
                  />
                </button>
              ) : (
                <div className="w-full h-full flex items-center justify-center">
                  <ImageIcon className="h-6 w-6 text-muted-foreground" />
                </div>
              )}
            </div>
          ))}
        </div>
      </>
    );
  }

  return (
    <>
      {lightboxSrc && (
        <ImageLightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} />
      )}
      <div className="divide-y divide-border">
        {items.map((item) => (
          <div key={item.id} className="py-2 first:pt-0 last:pb-0">
            {/* Subreddit + parent post info */}
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-0.5 flex-wrap">
              {item.subreddit && (
                <a
                  href={`https://reddit.com/${item.subreddit.startsWith('r/') ? item.subreddit : `r/${item.subreddit}`}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-primary hover:underline"
                >
                  {item.subreddit.startsWith('r/') ? item.subreddit : `r/${item.subreddit}`}
                </a>
              )}
              {item.link_title && (
                <>
                  <span className="text-muted-foreground/50">·</span>
                  <a
                    href={item.link_id ? `https://reddit.com/comments/${item.link_id.replace('t3_', '')}` : '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:text-primary hover:underline truncate max-w-[300px]"
                    title={item.link_title}
                  >
                    {item.link_title}
                  </a>
                </>
              )}
            </div>
            <div className="flex gap-2">
              {/* Inline thumbnail for posts with images */}
              {itemType === 'post' && item.attachment_id && (
                <button
                  className="shrink-0 w-16 h-16 rounded overflow-hidden bg-muted"
                  onClick={() => setLightboxSrc(`/api/core/attachments/${item.attachment_id}`)}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`/api/core/attachments/${item.attachment_id}`}
                    alt=""
                    className="w-full h-full object-cover hover:opacity-80 transition-opacity cursor-pointer"
                  />
                </button>
              )}
              <div className="min-w-0 flex-1">
                <p className="text-sm line-clamp-2">
                  {item.text_content || '(No content)'}
                </p>
                {item.item_created_at && (
                  <p className="text-xs text-muted-foreground mt-1">
                    {formatRelativeTime(item.item_created_at)}
                  </p>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

export function UserProfilePanel({
  username,
  providerId = 'reddit',
  accountId: initialAccountId,
  defaultExpanded = false,
  compact = false,
  onAnalysisComplete,
}: UserProfilePanelProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isQueued, setIsQueued] = useState(false);
  const [account, setAccount] = useState<AccountDetail | null>(null);
  const [accountId, setAccountId] = useState<number | undefined>(initialAccountId);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Profile items state
  const [activeTab, setActiveTab] = useState<'posts' | 'comments' | 'images'>('posts');
  const [posts, setPosts] = useState<ProfileItem[]>([]);
  const [comments, setComments] = useState<ProfileItem[]>([]);
  const [images, setImages] = useState<ProfileItem[]>([]);
  const [loadingItems, setLoadingItems] = useState(false);
  const [itemCounts, setItemCounts] = useState({ posts: 0, comments: 0, images: 0 });

  const cleanUsername = username.replace(/^u\//, '');

  // Fetch account by username if we don't have an accountId
  const fetchAccount = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      // First try by accountId if we have one
      let url: string;
      if (accountId) {
        url = `/api/core/accounts/${accountId}`;
      } else {
        url = `/api/core/accounts/by-username/${providerId}/${encodeURIComponent(cleanUsername)}`;
      }

      const response = await fetch(url, { credentials: 'include' });

      if (response.status === 404) {
        // Account not found - user hasn't been analyzed yet
        setAccount(null);
        return;
      }

      if (!response.ok) {
        throw new Error('Failed to fetch account');
      }

      const data: AccountDetail = await response.json();
      setAccount(data);
      setAccountId(data.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load profile');
    } finally {
      setLoading(false);
    }
  }, [accountId, providerId, cleanUsername]);

  // Fetch profile items for a specific type
  const fetchProfileItems = useCallback(async (itemType: 'post' | 'comment' | 'image') => {
    if (!accountId) return;

    setLoadingItems(true);
    try {
      const response = await fetch(
        `/api/core/accounts/${accountId}/profile-items?item_type=${itemType}&limit=10`,
        { credentials: 'include' }
      );

      if (!response.ok) {
        throw new Error('Failed to fetch items');
      }

      const data: ProfileItemsResponse = await response.json();

      switch (itemType) {
        case 'post':
          setPosts(data.items);
          setItemCounts(prev => ({ ...prev, posts: data.total }));
          break;
        case 'comment':
          setComments(data.items);
          setItemCounts(prev => ({ ...prev, comments: data.total }));
          break;
        case 'image':
          setImages(data.items);
          setItemCounts(prev => ({ ...prev, images: data.total }));
          break;
      }
    } catch (err) {
      console.error(`Failed to fetch ${itemType}s:`, err);
    } finally {
      setLoadingItems(false);
    }
  }, [accountId]);

  // Fetch account when expanded
  useEffect(() => {
    if (isExpanded && !account && !loading) {
      fetchAccount();
    }
  }, [isExpanded, account, loading, fetchAccount]);

  // Fetch profile items when tab changes
  useEffect(() => {
    if (isExpanded && accountId) {
      const itemType = activeTab === 'posts' ? 'post' : activeTab === 'comments' ? 'comment' : 'image';
      const items = activeTab === 'posts' ? posts : activeTab === 'comments' ? comments : images;

      // Only fetch if we don't have items yet
      if (items.length === 0) {
        fetchProfileItems(itemType);
      }
    }
  }, [isExpanded, accountId, activeTab, posts, comments, images, fetchProfileItems]);

  // Trigger analysis
  const handleAnalyze = useCallback(async (e?: React.MouseEvent) => {
    e?.stopPropagation();
    e?.preventDefault();

    if (isAnalyzing || isQueued) return;

    setIsAnalyzing(true);

    try {
      const response = await fetch('/api/core/accounts/analyze-username', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: cleanUsername }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to queue analysis');
      }

      setIsQueued(true);
      onAnalysisComplete?.();

      // Auto-expand to show results will come through
      setIsExpanded(true);

      // Poll for account data after analysis is queued
      const pollInterval = setInterval(async () => {
        try {
          const pollResponse = await fetch(
            `/api/core/accounts/by-username/${providerId}/${encodeURIComponent(cleanUsername)}`,
            { credentials: 'include' }
          );

          if (pollResponse.ok) {
            const data: AccountDetail = await pollResponse.json();
            if (data.latest_snapshot) {
              setAccount(data);
              setAccountId(data.id);
              clearInterval(pollInterval);
              setIsQueued(false);
              // Clear items to force refresh
              setPosts([]);
              setComments([]);
              setImages([]);
            }
          }
        } catch {
          // Ignore polling errors
        }
      }, 3000);

      // Stop polling after 2 minutes
      setTimeout(() => {
        clearInterval(pollInterval);
        setIsQueued(false);
      }, 120000);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to analyze user';
      setError(errorMsg);
      console.error('Failed to analyze user:', err);
    } finally {
      setIsAnalyzing(false);
    }
  }, [cleanUsername, isAnalyzing, isQueued, onAnalysisComplete, providerId]);

  const toggleExpand = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    setIsExpanded(!isExpanded);
  };

  const snapshot = account?.latest_snapshot;
  const hasAnalysis = !!snapshot;
  const isAnalyzed = account?.analysis_state === 'done';

  return (
    <div className={cn('w-full', compact ? '' : '')}>
      {/* Header Row */}
      <div className="flex items-center gap-2 flex-wrap">
        <a
          href={`https://reddit.com/u/${cleanUsername}`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-sm hover:text-primary hover:underline"
          onClick={(e) => e.stopPropagation()}
        >
          <User className="h-3 w-3" />
          u/{cleanUsername}
        </a>

        {/* Analyze Button */}
        <Button
          variant="ghost"
          size="sm"
          onClick={handleAnalyze}
          disabled={isAnalyzing || isQueued}
          className="h-6 px-2"
          title={isQueued ? 'Analysis queued' : `Analyze u/${cleanUsername}`}
        >
          {isAnalyzing ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : isQueued ? (
            <CheckCircle className="h-3 w-3 text-emerald-500" />
          ) : (
            <Sparkles className="h-3 w-3" />
          )}
          <span className="ml-1 text-xs">
            {isQueued ? 'Queued' : isAnalyzed ? 'Re-analyze' : 'Analyze'}
          </span>
        </Button>

        {/* Expand/Collapse Button */}
        <Button
          variant="ghost"
          size="sm"
          onClick={toggleExpand}
          className="h-6 px-2"
        >
          {isExpanded ? (
            <ChevronUp className="h-3 w-3" />
          ) : (
            <ChevronDown className="h-3 w-3" />
          )}
          <span className="ml-1 text-xs">
            {isExpanded ? 'Hide Profile' : hasAnalysis ? 'Show Profile' : 'Show Details'}
          </span>
        </Button>

        {/* Full Profile Link */}
        {accountId && (
          <Link
            href={`/profile/${accountId}`}
            className="text-xs text-muted-foreground hover:text-primary hover:underline flex items-center gap-1"
            onClick={(e) => e.stopPropagation()}
          >
            <ExternalLink className="h-3 w-3" />
            Full Profile
          </Link>
        )}

        {/* Analysis indicator */}
        {hasAnalysis && !isExpanded && (
          <Badge variant="secondary" className="text-xs h-5">
            Analyzed
          </Badge>
        )}
      </div>

      {/* Expandable Panel */}
      {isExpanded && (
        <Card className="mt-3 p-4 bg-muted/30">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : error ? (
            <div className="text-center py-4">
              <p className="text-sm text-destructive">{error}</p>
              <Button variant="outline" size="sm" onClick={fetchAccount} className="mt-2">
                Retry
              </Button>
            </div>
          ) : !account ? (
            <div className="text-center py-6">
              <User className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
              <p className="text-sm text-muted-foreground mb-3">
                This user hasn't been analyzed yet
              </p>
              <Button
                variant="default"
                size="sm"
                onClick={handleAnalyze}
                disabled={isAnalyzing || isQueued}
              >
                {isAnalyzing ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-1" />
                ) : (
                  <Sparkles className="h-4 w-4 mr-1" />
                )}
                {isQueued ? 'Analysis Queued...' : 'Analyze Now'}
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Summary Section */}
              {snapshot?.summary_text ? (
                <div>
                  <h4 className="text-sm font-medium mb-2">Profile Summary</h4>
                  <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                    {snapshot.summary_text}
                  </p>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground italic">
                  No summary available yet. Click "Re-analyze" to generate one.
                </div>
              )}

              {/* Signals */}
              {snapshot?.signals_json && (
                <div>
                  <h4 className="text-sm font-medium mb-1">Signals</h4>
                  <SignalsBadges signals={snapshot.signals_json} />
                </div>
              )}

              {/* Risk Flags */}
              {snapshot?.risk_flags_json && (
                <div>
                  <h4 className="text-sm font-medium mb-1">Risk Flags</h4>
                  <RiskFlagsBadges riskFlags={snapshot.risk_flags_json} />
                </div>
              )}

              {/* Analysis timestamp */}
              {snapshot?.fetched_at && (
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Clock className="h-3 w-3" />
                  Analyzed {formatRelativeTime(snapshot.fetched_at)}
                </div>
              )}

              {/* Profile Items Tabs */}
              <div className="pt-2 border-t border-border">
                <Tabs
                  value={activeTab}
                  onValueChange={(v) => setActiveTab(v as 'posts' | 'comments' | 'images')}
                >
                  <TabsList className="h-8">
                    <TabsTrigger value="posts" className="text-xs h-6 px-2">
                      <FileText className="h-3 w-3 mr-1" />
                      Posts {itemCounts.posts > 0 && `(${itemCounts.posts})`}
                    </TabsTrigger>
                    <TabsTrigger value="comments" className="text-xs h-6 px-2">
                      <MessageCircle className="h-3 w-3 mr-1" />
                      Comments {itemCounts.comments > 0 && `(${itemCounts.comments})`}
                    </TabsTrigger>
                    <TabsTrigger value="images" className="text-xs h-6 px-2">
                      <ImageIcon className="h-3 w-3 mr-1" />
                      Images {itemCounts.images > 0 && `(${itemCounts.images})`}
                    </TabsTrigger>
                  </TabsList>

                  <TabsContent value="posts" className="mt-3">
                    <ProfileItemsList
                      items={posts}
                      itemType="post"
                      loading={loadingItems && activeTab === 'posts'}
                    />
                  </TabsContent>

                  <TabsContent value="comments" className="mt-3">
                    <ProfileItemsList
                      items={comments}
                      itemType="comment"
                      loading={loadingItems && activeTab === 'comments'}
                    />
                  </TabsContent>

                  <TabsContent value="images" className="mt-3">
                    <ProfileItemsList
                      items={images}
                      itemType="image"
                      loading={loadingItems && activeTab === 'images'}
                    />
                  </TabsContent>
                </Tabs>

                {/* View Full Profile link */}
                {accountId && (
                  <div className="mt-3 pt-3 border-t border-border">
                    <Link
                      href={`/profile/${accountId}`}
                      className="text-sm text-primary hover:underline flex items-center gap-1"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <ExternalLink className="h-4 w-4" />
                      View Full Profile
                    </Link>
                  </div>
                )}
              </div>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
