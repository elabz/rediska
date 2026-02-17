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
  Search,
  ArrowUpDown,
  Star,
} from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ContactButton } from '@/components/ContactButton';
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
  is_starred: boolean;
  starred_at: string | null;
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
  starred: number;
}

type DirectoryTab = 'analyzed' | 'contacted' | 'engaged' | 'starred';
type SortOption = 'newest' | 'oldest' | 'alphabetical';

const SORT_OPTIONS: { value: SortOption; label: string }[] = [
  { value: 'newest', label: 'Newest First' },
  { value: 'oldest', label: 'Oldest First' },
  { value: 'alphabetical', label: 'A-Z' },
];

const TABS: { key: DirectoryTab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { key: 'analyzed', label: 'Analyzed', icon: Sparkles },
  { key: 'contacted', label: 'Contacted', icon: MessageSquare },
  { key: 'engaged', label: 'Engaged', icon: CheckCircle2 },
  { key: 'starred', label: 'Starred', icon: Star },
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

function DirectoryEntryCard({
  entry,
  onToggleStar,
}: {
  entry: DirectoryEntry;
  onToggleStar: (id: number) => void;
}) {
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
          <div className="flex items-center gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={(e) => {
                e.preventDefault();
                onToggleStar(entry.id);
              }}
              className={cn(
                "p-1 rounded transition-colors",
                entry.is_starred
                  ? "text-yellow-500 hover:text-yellow-600"
                  : "text-muted-foreground hover:text-foreground"
              )}
              title={entry.is_starred ? "Unstar" : "Star"}
            >
              <Star className={cn("h-4 w-4", entry.is_starred && "fill-current")} />
            </button>
            <ContactButton
              username={entry.external_username}
              providerId={entry.provider_id}
              variant="icon"
            />
            <a
              href={redditProfileUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              <ExternalLink className="h-4 w-4" />
            </a>
          </div>
        </div>
      </Card>
    </Link>
  );
}

export default function DirectoriesPage() {
  const [activeTab, setActiveTab] = useState<DirectoryTab>('analyzed');
  const [entries, setEntries] = useState<DirectoryEntry[]>([]);
  const [counts, setCounts] = useState<DirectoryCounts>({ analyzed: 0, contacted: 0, engaged: 0, starred: 0 });
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState<SortOption>('newest');
  const [analyzeUsername, setAnalyzeUsername] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeResult, setAnalyzeResult] = useState<string | null>(null);

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

  const fetchDirectory = useCallback(async (tab: DirectoryTab, newOffset = 0, search?: string, sort?: SortOption) => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams({
        limit: String(LIMIT),
        offset: String(newOffset),
      });

      const actualSearch = search ?? searchQuery;
      const actualSort = sort ?? sortBy;

      if (actualSearch.trim()) {
        params.set('search', actualSearch.trim());
      }
      if (actualSort !== 'newest') {
        params.set('sort_by', actualSort);
      }

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
  }, [searchQuery, sortBy]);

  const handleAnalyzeUsername = useCallback(async () => {
    const username = analyzeUsername.trim().replace(/^u\//, '');
    if (!username) return;

    setAnalyzing(true);
    setAnalyzeResult(null);

    try {
      const response = await fetch('/api/core/accounts/analyze-username', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to queue analysis');
      }

      setAnalyzeResult(`Analysis queued for u/${username}`);
      setAnalyzeUsername('');
    } catch (err) {
      setAnalyzeResult(err instanceof Error ? err.message : 'Failed to analyze');
    } finally {
      setAnalyzing(false);
    }
  }, [analyzeUsername]);

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

  const handleSearchSubmit = () => {
    setOffset(0);
    fetchDirectory(activeTab, 0);
  };

  const handleSortChange = (newSort: SortOption) => {
    setSortBy(newSort);
    setOffset(0);
    fetchDirectory(activeTab, 0, searchQuery, newSort);
  };

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

      // Update the entry in the local list
      setEntries((prev) =>
        prev.map((e) =>
          e.id === accountId
            ? { ...e, is_starred: result.is_starred, starred_at: result.starred_at }
            : e
        )
      );

      // Refresh counts
      fetchCounts();
    } catch (err) {
      console.error('Failed to toggle star:', err);
    }
  }, [fetchCounts]);

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

      {/* Analyze Username */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
            u/
          </span>
          <Input
            type="text"
            placeholder="Enter Reddit username to analyze..."
            value={analyzeUsername}
            onChange={(e) => setAnalyzeUsername(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                handleAnalyzeUsername();
              }
            }}
            className="pl-8 h-10"
          />
        </div>
        <Button
          onClick={handleAnalyzeUsername}
          disabled={analyzing || !analyzeUsername.trim()}
          className="h-10"
        >
          {analyzing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <>
              <Sparkles className="h-4 w-4 mr-2" />
              Analyze
            </>
          )}
        </Button>
      </div>
      {analyzeResult && (
        <p className="text-sm text-muted-foreground">{analyzeResult}</p>
      )}

      {/* Search and Sort */}
      <div className="flex gap-2 items-center">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            type="text"
            placeholder="Search by username or summary..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                handleSearchSubmit();
              }
            }}
            className="pl-9 h-9"
          />
        </div>
        <Button variant="secondary" size="sm" onClick={handleSearchSubmit} className="h-9">
          <Search className="h-4 w-4" />
        </Button>
        <Select value={sortBy} onValueChange={(v) => handleSortChange(v as SortOption)}>
          <SelectTrigger className="w-[160px] h-9">
            <ArrowUpDown className="h-4 w-4 mr-2" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SORT_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
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
          icon={activeTab === 'analyzed' ? '🔬' : activeTab === 'contacted' ? '💬' : activeTab === 'starred' ? '⭐' : '🤝'}
          title={`No ${activeTab} contacts`}
          description={
            activeTab === 'analyzed'
              ? "No profiles have been analyzed yet. Save leads and analyze them to populate this directory."
              : activeTab === 'contacted'
              ? "No contacts have been made yet. Reach out to analyzed leads to populate this directory."
              : activeTab === 'starred'
              ? "No contacts have been starred yet. Star contacts to quickly find them later."
              : "No contacts have responded yet. Engaged contacts will appear here when they reply."
          }
        />
      ) : (
        <>
          <div className="space-y-3">
            {entries.map((entry) => (
              <DirectoryEntryCard key={entry.id} entry={entry} onToggleStar={handleToggleStar} />
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
