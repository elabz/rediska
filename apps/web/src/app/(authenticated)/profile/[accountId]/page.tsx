'use client';

import { useState, useCallback, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  Loader2,
  User,
  ExternalLink,
  RefreshCw,
  MessageSquare,
  Sparkles,
  AlertTriangle,
  CheckCircle,
  Clock,
  FileText,
  MessageCircle,
  Image as ImageIcon,
  ChevronRight,
  ArrowLeft,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components';
import { cn } from '@/lib/utils';

// =============================================================================
// Types
// =============================================================================

interface ProfileSnapshot {
  id: number;
  fetched_at: string;
  summary_text: string | null;
  signals_json: Record<string, string[] | string> | null;
  risk_flags_json: Record<string, boolean | string> | null;
  model_info_json: Record<string, string> | null;
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
  first_contacted_at: string | null;
  first_inbound_after_contact_at: string | null;
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
  remote_visibility: string;
  created_at: string;
}

interface ConversationSummary {
  id: number;
  identity_id: number;
  last_activity_at: string | null;
  message_count: number;
  created_at: string;
}

type ContentTab = 'posts' | 'comments' | 'images';

// =============================================================================
// Helper Functions
// =============================================================================

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffDays < 1) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function getRemoteStatusColor(status: string): string {
  switch (status) {
    case 'active': return 'bg-green-500/10 text-green-600 border-green-500/20';
    case 'deleted': return 'bg-red-500/10 text-red-600 border-red-500/20';
    case 'suspended': return 'bg-orange-500/10 text-orange-600 border-orange-500/20';
    default: return 'bg-gray-500/10 text-gray-600 border-gray-500/20';
  }
}

function getAnalysisStateColor(state: string): string {
  switch (state) {
    case 'analyzed': return 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20';
    case 'needs_refresh': return 'bg-yellow-500/10 text-yellow-600 border-yellow-500/20';
    default: return 'bg-gray-500/10 text-gray-600 border-gray-500/20';
  }
}

// =============================================================================
// Components
// =============================================================================

function ProfileHeader({
  account,
  onAnalyze,
  analyzing,
}: {
  account: AccountDetail;
  onAnalyze: () => void;
  analyzing: boolean;
}) {
  const redditProfileUrl = `https://reddit.com/u/${account.external_username}`;

  return (
    <div className="flex items-start gap-6">
      {/* Avatar */}
      <div className="w-20 h-20 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
        <User className="h-10 w-10 text-primary" />
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-2xl font-bold">u/{account.external_username}</h1>
          <Badge variant="secondary">{account.provider_id}</Badge>
          <Badge variant="outline" className={getRemoteStatusColor(account.remote_status)}>
            {account.remote_status}
          </Badge>
          <Badge variant="outline" className={getAnalysisStateColor(account.analysis_state)}>
            {account.analysis_state === 'analyzed' ? (
              <><Sparkles className="h-3 w-3 mr-1" />Analyzed</>
            ) : account.analysis_state === 'needs_refresh' ? (
              <><RefreshCw className="h-3 w-3 mr-1" />Needs Refresh</>
            ) : (
              'Not Analyzed'
            )}
          </Badge>
        </div>

        {/* States */}
        <div className="flex items-center gap-4 mt-3 text-sm text-muted-foreground">
          {account.contact_state === 'contacted' && (
            <span className="flex items-center gap-1">
              <MessageSquare className="h-4 w-4" />
              Contacted
              {account.first_contacted_at && (
                <span className="text-xs">({formatDate(account.first_contacted_at)})</span>
              )}
            </span>
          )}
          {account.engagement_state === 'engaged' && (
            <span className="flex items-center gap-1 text-emerald-600">
              <CheckCircle className="h-4 w-4" />
              Engaged
            </span>
          )}
          {account.first_analyzed_at && (
            <span className="flex items-center gap-1">
              <Clock className="h-4 w-4" />
              First analyzed {formatDate(account.first_analyzed_at)}
            </span>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-3 mt-4">
          <Button
            variant="default"
            size="sm"
            onClick={onAnalyze}
            disabled={analyzing}
          >
            {analyzing ? (
              <><Loader2 className="h-4 w-4 animate-spin mr-2" />Analyzing...</>
            ) : (
              <><Sparkles className="h-4 w-4 mr-2" />{account.analysis_state === 'analyzed' ? 'Re-analyze' : 'Analyze'}</>
            )}
          </Button>
          <a
            href={redditProfileUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            <Button variant="outline" size="sm">
              <ExternalLink className="h-4 w-4 mr-2" />
              View on Reddit
            </Button>
          </a>
        </div>
      </div>
    </div>
  );
}

function ProfileSummary({ snapshot }: { snapshot: ProfileSnapshot | null }) {
  if (!snapshot) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Profile Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState
            icon="🔬"
            title="No analysis available"
            description="Click 'Analyze' to generate a profile summary for this account."
          />
        </CardContent>
      </Card>
    );
  }

  const signals = snapshot.signals_json;
  const riskFlags = snapshot.risk_flags_json;
  const hasRiskFlags = riskFlags && Object.values(riskFlags).some(v => v === true);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-lg">Profile Summary</CardTitle>
            <CardDescription>
              Generated {formatDate(snapshot.fetched_at)}
              {snapshot.model_info_json?.model && (
                <span className="ml-2">• {snapshot.model_info_json.model}</span>
              )}
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Summary Text */}
        {snapshot.summary_text && (
          <div className="prose prose-sm dark:prose-invert max-w-none">
            <p className="whitespace-pre-wrap">{snapshot.summary_text}</p>
          </div>
        )}

        {/* Signals */}
        {signals && Object.keys(signals).length > 0 && (
          <div>
            <h4 className="text-sm font-medium mb-2">Extracted Signals</h4>
            <div className="flex flex-wrap gap-2">
              {Object.entries(signals).map(([key, value]) => {
                if (Array.isArray(value)) {
                  return value.map((v, i) => (
                    <Badge key={`${key}-${i}`} variant="secondary" className="text-xs">
                      {key}: {v}
                    </Badge>
                  ));
                }
                return (
                  <Badge key={key} variant="secondary" className="text-xs">
                    {key}: {String(value)}
                  </Badge>
                );
              })}
            </div>
          </div>
        )}

        {/* Risk Flags */}
        {hasRiskFlags && (
          <div className="p-3 rounded-lg bg-orange-500/10 border border-orange-500/20">
            <h4 className="text-sm font-medium text-orange-600 flex items-center gap-2 mb-2">
              <AlertTriangle className="h-4 w-4" />
              Risk Flags
            </h4>
            <div className="flex flex-wrap gap-2">
              {Object.entries(riskFlags!).filter(([, v]) => v === true).map(([key]) => (
                <Badge key={key} variant="outline" className="text-xs text-orange-600 border-orange-500/30">
                  {key}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ContentTabs({
  accountId,
  activeTab,
  setActiveTab,
}: {
  accountId: number;
  activeTab: ContentTab;
  setActiveTab: (tab: ContentTab) => void;
}) {
  const [items, setItems] = useState<ProfileItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [offset, setOffset] = useState(0);
  const LIMIT = 10;

  const fetchItems = useCallback(async (tab: ContentTab, newOffset = 0) => {
    setLoading(true);
    try {
      const itemType = tab === 'posts' ? 'post' : tab === 'comments' ? 'comment' : 'image';
      const params = new URLSearchParams({
        item_type: itemType,
        offset: String(newOffset),
        limit: String(LIMIT),
      });

      const response = await fetch(`/api/core/accounts/${accountId}/profile-items?${params}`, {
        credentials: 'include',
      });

      if (response.ok) {
        const data = await response.json();
        setItems(data.items);
        setTotal(data.total);
        setOffset(newOffset);
      }
    } catch (err) {
      console.error('Failed to fetch items:', err);
    } finally {
      setLoading(false);
    }
  }, [accountId]);

  useEffect(() => {
    fetchItems(activeTab, 0);
  }, [activeTab, fetchItems]);

  const tabs = [
    { key: 'posts' as ContentTab, label: 'Posts', icon: FileText },
    { key: 'comments' as ContentTab, label: 'Comments', icon: MessageCircle },
    { key: 'images' as ContentTab, label: 'Images', icon: ImageIcon },
  ];

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-lg">Content</CardTitle>
      </CardHeader>
      <CardContent>
        {/* Tabs */}
        <div className="flex gap-1 p-1 bg-muted rounded-lg mb-4">
          {tabs.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => {
                setActiveTab(key);
                setOffset(0);
              }}
              className={cn(
                "flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors",
                activeTab === key
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
        </div>

        {/* Content */}
        {loading && items.length === 0 ? (
          <div className="flex items-center justify-center h-32">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            <p className="text-sm">No {activeTab} found for this account</p>
          </div>
        ) : (
          <>
            <div className="space-y-3">
              {items.map((item) => (
                <div
                  key={item.id}
                  className="p-3 rounded-lg border bg-card"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      {item.text_content && (
                        <p className="text-sm line-clamp-3">{item.text_content}</p>
                      )}
                      {item.attachment_id && !item.text_content && (
                        <p className="text-sm text-muted-foreground italic">[Image attachment]</p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {item.remote_visibility !== 'visible' && (
                        <Badge variant="outline" className="text-xs text-orange-600 border-orange-500/30">
                          {item.remote_visibility.replace(/_/g, ' ')}
                        </Badge>
                      )}
                      {item.item_created_at && (
                        <span className="text-xs text-muted-foreground">
                          {formatDate(item.item_created_at)}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Pagination */}
            {total > LIMIT && (
              <div className="flex items-center justify-center gap-4 mt-4">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fetchItems(activeTab, Math.max(0, offset - LIMIT))}
                  disabled={offset === 0 || loading}
                >
                  Previous
                </Button>
                <span className="text-sm text-muted-foreground">
                  {offset + 1}-{Math.min(offset + LIMIT, total)} of {total}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fetchItems(activeTab, offset + LIMIT)}
                  disabled={offset + LIMIT >= total || loading}
                >
                  Next
                </Button>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function ConversationHistory({
  accountId,
}: {
  accountId: number;
}) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchConversations = async () => {
      try {
        const response = await fetch(`/api/core/accounts/${accountId}/conversations`, {
          credentials: 'include',
        });

        if (response.ok) {
          const data = await response.json();
          setConversations(data.conversations);
          setTotal(data.total);
        }
      } catch (err) {
        console.error('Failed to fetch conversations:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchConversations();
  }, [accountId]);

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Conversation History</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center h-24">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (conversations.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Conversation History</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-6 text-muted-foreground">
            <MessageSquare className="h-8 w-8 mx-auto mb-2 opacity-50" />
            <p className="text-sm">No conversations with this account</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">Conversation History</CardTitle>
          <Badge variant="secondary">{total} conversation{total !== 1 ? 's' : ''}</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {conversations.map((conv) => (
            <Link
              key={conv.id}
              href={`/inbox/${conv.id}`}
              className="flex items-center justify-between p-3 rounded-lg border bg-card hover:bg-muted/50 transition-colors"
            >
              <div className="flex items-center gap-3">
                <MessageSquare className="h-5 w-5 text-muted-foreground" />
                <div>
                  <p className="text-sm font-medium">
                    {conv.message_count} message{conv.message_count !== 1 ? 's' : ''}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {conv.last_activity_at ? formatDate(conv.last_activity_at) : 'No activity'}
                  </p>
                </div>
              </div>
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            </Link>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// =============================================================================
// Main Page
// =============================================================================

export default function ProfilePage() {
  const params = useParams();
  const router = useRouter();
  const accountId = Number(params.accountId);

  const [account, setAccount] = useState<AccountDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [activeTab, setActiveTab] = useState<ContentTab>('posts');

  const fetchAccount = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`/api/core/accounts/${accountId}`, {
        credentials: 'include',
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to fetch account');
      }

      const data = await response.json();
      setAccount(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, [accountId]);

  useEffect(() => {
    if (accountId) {
      fetchAccount();
    }
  }, [accountId, fetchAccount]);

  const handleAnalyze = async () => {
    setAnalyzing(true);
    try {
      const response = await fetch(`/api/core/accounts/${accountId}/analyze`, {
        method: 'POST',
        credentials: 'include',
      });

      if (response.ok) {
        // Refresh account data after a delay
        setTimeout(fetchAccount, 2000);
      }
    } catch (err) {
      console.error('Failed to trigger analysis:', err);
    } finally {
      setAnalyzing(false);
    }
  };

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  if (error || !account) {
    return (
      <div className="max-w-4xl mx-auto">
        <Card className="p-8">
          <div className="text-center">
            <User className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-destructive font-medium">{error || 'Account not found'}</p>
            <Button variant="outline" onClick={() => router.back()} className="mt-4">
              Go Back
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Back Button */}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => router.back()}
        className="gap-2"
      >
        <ArrowLeft className="h-4 w-4" />
        Back
      </Button>

      {/* Profile Header */}
      <Card className="p-6">
        <ProfileHeader
          account={account}
          onAnalyze={handleAnalyze}
          analyzing={analyzing}
        />
      </Card>

      {/* Profile Summary */}
      <ProfileSummary snapshot={account.latest_snapshot} />

      {/* Content Tabs */}
      <ContentTabs
        accountId={accountId}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
      />

      {/* Conversation History */}
      <ConversationHistory accountId={accountId} />
    </div>
  );
}
