'use client';

import { useState, useCallback, useEffect } from 'react';
import Link from 'next/link';
import {
  Loader2,
  RefreshCw,
  User,
  MessageSquare,
  CheckCircle2,
  ExternalLink,
  Sparkles,
  AlertCircle,
} from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components';
import { cn } from '@/lib/utils';

interface DirectoryEntry {
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
  latest_summary: string | null;
  lead_count: number;
}

interface DirectoryResponse {
  entries: DirectoryEntry[];
  total: number;
  directory_type: string;
}

interface DirectoryCounts {
  analyzed: number;
  contacted: number;
  engaged: number;
}

type DirectoryTab = 'analyzed' | 'contacted' | 'engaged';

const TABS: { key: DirectoryTab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { key: 'analyzed', label: 'Analyzed', icon: Sparkles },
  { key: 'contacted', label: 'Contacted', icon: MessageSquare },
  { key: 'engaged', label: 'Engaged', icon: CheckCircle2 },
];

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffDays < 1) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return `${diffDays}d ago`;

  // Include year if not current year
  const isCurrentYear = date.getFullYear() === now.getFullYear();
  if (isCurrentYear) {
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function DirectoryEntryCard({ entry }: { entry: DirectoryEntry }) {
  const redditProfileUrl = `https://reddit.com/u/${entry.external_username}`;

  return (
    <Link href={`/profile/${entry.id}`}>
      <Card className="p-4 hover:bg-muted/30 transition-colors cursor-pointer">
        <div className="flex items-start gap-4">
          {/* Avatar */}
          <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
            <User className="h-5 w-5 text-primary" />
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-medium truncate">u/{entry.external_username}</span>
            <Badge variant="secondary" className="text-xs h-5 px-1.5">
              {entry.provider_id}
            </Badge>
            {entry.remote_status !== 'active' && (
              <Badge variant="outline" className="text-xs h-5 px-1.5 text-muted-foreground">
                {entry.remote_status}
              </Badge>
            )}
          </div>

          {/* Summary */}
          {entry.latest_summary && (
            <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
              {entry.latest_summary}
            </p>
          )}

          {/* Meta */}
          <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
            {entry.first_analyzed_at && (
              <span className="flex items-center gap-1">
                <Sparkles className="h-3 w-3" />
                Analyzed {formatDate(entry.first_analyzed_at)}
              </span>
            )}
            {entry.first_contacted_at && (
              <span className="flex items-center gap-1">
                <MessageSquare className="h-3 w-3" />
                Contacted {formatDate(entry.first_contacted_at)}
              </span>
            )}
            {entry.first_inbound_after_contact_at && (
              <span className="flex items-center gap-1">
                <CheckCircle2 className="h-3 w-3" />
                Engaged {formatDate(entry.first_inbound_after_contact_at)}
              </span>
            )}
            {entry.lead_count > 0 && (
              <span>{entry.lead_count} lead{entry.lead_count !== 1 ? 's' : ''}</span>
            )}
          </div>
        </div>

          {/* Actions */}
          <a
            href={redditProfileUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-muted-foreground hover:text-foreground transition-colors shrink-0"
            onClick={(e) => e.stopPropagation()}
          >
            <ExternalLink className="h-4 w-4" />
          </a>
        </div>
      </Card>
    </Link>
  );
}

export default function DirectoriesPage() {
  const [activeTab, setActiveTab] = useState<DirectoryTab>('analyzed');
  const [entries, setEntries] = useState<DirectoryEntry[]>([]);
  const [counts, setCounts] = useState<DirectoryCounts>({ analyzed: 0, contacted: 0, engaged: 0 });
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const LIMIT = 20;

  const fetchCounts = useCallback(async () => {
    try {
      const response = await fetch('/api/core/directories/counts', {
        credentials: 'include',
      });

      if (response.ok) {
        const data: DirectoryCounts = await response.json();
        setCounts(data);
      }
    } catch (err) {
      console.error('Failed to fetch counts:', err);
    }
  }, []);

  const fetchDirectory = useCallback(async (tab: DirectoryTab, newOffset = 0) => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams({
        limit: String(LIMIT),
        offset: String(newOffset),
      });

      const response = await fetch(`/api/core/directories/${tab}?${params.toString()}`, {
        credentials: 'include',
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to fetch directory');
      }

      const data: DirectoryResponse = await response.json();
      setEntries(data.entries);
      setTotal(data.total);
      setOffset(newOffset);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCounts();
  }, [fetchCounts]);

  useEffect(() => {
    fetchDirectory(activeTab);
  }, [activeTab, fetchDirectory]);

  const handleTabChange = (tab: DirectoryTab) => {
    setActiveTab(tab);
    setOffset(0);
  };

  const refresh = () => {
    fetchCounts();
    fetchDirectory(activeTab);
  };

  if (loading && entries.length === 0) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  if (error && entries.length === 0) {
    return (
      <div className="max-w-4xl mx-auto">
        <Card className="p-8">
          <div className="text-center">
            <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
            <p className="text-destructive font-medium">{error}</p>
            <Button variant="outline" onClick={refresh} className="mt-4">
              Try Again
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  const totalContacts = counts.analyzed + counts.contacted + counts.engaged;

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Directories</h1>
          <p className="text-muted-foreground mt-1">
            {totalContacts} total contact{totalContacts !== 1 ? 's' : ''} across all directories
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={refresh} disabled={loading}>
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
        </Button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-muted rounded-lg">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => handleTabChange(key)}
            className={cn(
              "flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors",
              activeTab === key
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
            <Badge
              variant="secondary"
              className={cn(
                "ml-1 h-5 px-1.5 text-xs",
                activeTab === key ? "bg-muted" : ""
              )}
            >
              {counts[key]}
            </Badge>
          </button>
        ))}
      </div>

      {/* Content */}
      {entries.length === 0 ? (
        <EmptyState
          icon={activeTab === 'analyzed' ? '🔬' : activeTab === 'contacted' ? '💬' : '🤝'}
          title={`No ${activeTab} contacts`}
          description={
            activeTab === 'analyzed'
              ? "No profiles have been analyzed yet. Save leads and analyze them to populate this directory."
              : activeTab === 'contacted'
              ? "No contacts have been made yet. Reach out to analyzed leads to populate this directory."
              : "No contacts have responded yet. Engaged contacts will appear here when they reply."
          }
        />
      ) : (
        <>
          <div className="space-y-3">
            {entries.map((entry) => (
              <DirectoryEntryCard key={entry.id} entry={entry} />
            ))}
          </div>

          {/* Pagination */}
          {total > LIMIT && (
            <div className="flex items-center justify-center gap-4">
              <Button
                variant="outline"
                onClick={() => fetchDirectory(activeTab, Math.max(0, offset - LIMIT))}
                disabled={offset === 0 || loading}
              >
                Previous
              </Button>
              <span className="text-sm text-muted-foreground">
                {offset + 1}-{Math.min(offset + LIMIT, total)} of {total}
              </span>
              <Button
                variant="outline"
                onClick={() => fetchDirectory(activeTab, offset + LIMIT)}
                disabled={offset + LIMIT >= total || loading}
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
