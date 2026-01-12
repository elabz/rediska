'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';
import { Loader2, Search, MessageSquare, FileText, User, Filter, X, ExternalLink } from 'lucide-react';
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
import { EmptyState } from '@/components';

interface SearchHit {
  id: string;
  score: number;
  source: {
    doc_type?: string;
    text?: string;
    provider_id?: string;
    identity_id?: string;
    account_id?: string;
    conversation_id?: string;
    message_id?: string;
    lead_post_id?: string;
    source_location?: string;
    created_at?: string;
    remote_status?: string;
    remote_visibility?: string;
  };
}

interface SearchResponse {
  total: number;
  hits: SearchHit[];
  max_score: number | null;
}

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function getDocTypeInfo(docType: string) {
  switch (docType) {
    case 'message':
      return { icon: MessageSquare, label: 'Message', color: 'bg-blue-500/10 text-blue-600' };
    case 'lead_post':
      return { icon: FileText, label: 'Lead Post', color: 'bg-amber-500/10 text-amber-600' };
    case 'profile':
      return { icon: User, label: 'Profile', color: 'bg-purple-500/10 text-purple-600' };
    case 'conversation':
      return { icon: MessageSquare, label: 'Conversation', color: 'bg-emerald-500/10 text-emerald-600' };
    default:
      return { icon: FileText, label: docType, color: 'bg-muted text-muted-foreground' };
  }
}

function SearchResultCard({ hit }: { hit: SearchHit }) {
  const docType = hit.source.doc_type || 'unknown';
  const { icon: Icon, label, color } = getDocTypeInfo(docType);
  const text = hit.source.text || '';
  const preview = text.length > 200 ? text.substring(0, 200) + '...' : text;

  // Determine link based on doc type
  let linkHref: string | null = null;
  if (docType === 'message' && hit.source.conversation_id) {
    linkHref = `/inbox/${hit.source.conversation_id}`;
  } else if (docType === 'conversation') {
    const convId = hit.id.split(':')[1];
    if (convId) linkHref = `/inbox/${convId}`;
  }

  const content = (
    <div className="p-4 hover:bg-muted/50 transition-colors border-b border-border last:border-b-0">
      <div className="flex items-start gap-3">
        <div className={`p-2 rounded-lg ${color}`}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <Badge variant="outline" className="text-xs">
              {label}
            </Badge>
            {hit.source.provider_id && (
              <Badge variant="secondary" className="text-xs">
                {hit.source.provider_id}
              </Badge>
            )}
            {hit.source.source_location && (
              <span className="text-xs text-muted-foreground">
                r/{hit.source.source_location}
              </span>
            )}
            <span className="text-xs text-muted-foreground ml-auto">
              Score: {hit.score.toFixed(2)}
            </span>
          </div>
          <p className="text-sm whitespace-pre-wrap break-words line-clamp-3">
            {preview || <span className="text-muted-foreground italic">No text content</span>}
          </p>
          <div className="flex items-center gap-3 mt-2 text-xs text-muted-foreground">
            {hit.source.created_at && (
              <span>{formatDate(hit.source.created_at)}</span>
            )}
            {hit.source.remote_visibility && hit.source.remote_visibility !== 'visible' && (
              <Badge variant="secondary" className="text-xs">
                {hit.source.remote_visibility}
              </Badge>
            )}
            {linkHref && (
              <span className="flex items-center gap-1 text-primary">
                <ExternalLink className="h-3 w-3" />
                View
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );

  if (linkHref) {
    return <Link href={linkHref}>{content}</Link>;
  }
  return content;
}

export default function SearchPage() {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState('hybrid');
  const [docTypeFilter, setDocTypeFilter] = useState<string>('all');
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  const performSearch = useCallback(async (searchQuery: string) => {
    if (!searchQuery.trim()) {
      setResults(null);
      setHasSearched(false);
      return;
    }

    setLoading(true);
    setError(null);
    setHasSearched(true);

    try {
      const requestBody: Record<string, unknown> = {
        query: searchQuery,
        mode,
        limit: 50,
      };

      if (docTypeFilter && docTypeFilter !== 'all') {
        requestBody.doc_types = [docTypeFilter];
      }

      const response = await fetch('/api/core/search', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        if (response.status === 401) {
          throw new Error('Please log in to search');
        }
        const data = await response.json();
        throw new Error(data.detail?.error || data.detail || 'Search failed');
      }

      const data: SearchResponse = await response.json();
      setResults(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
      setResults(null);
    } finally {
      setLoading(false);
    }
  }, [mode, docTypeFilter]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    performSearch(query);
  };

  const clearFilters = () => {
    setMode('hybrid');
    setDocTypeFilter('all');
  };

  const hasFilters = mode !== 'hybrid' || (docTypeFilter && docTypeFilter !== 'all');

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Search</h1>
        <p className="text-muted-foreground mt-1">
          Search across conversations, messages, leads, and profiles
        </p>
      </div>

      {/* Search Form */}
      <form onSubmit={handleSubmit}>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              type="text"
              placeholder="Search for anything..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="pl-10 h-11"
              autoFocus
            />
          </div>
          <Button type="submit" disabled={loading || !query.trim()} className="h-11 px-6">
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              'Search'
            )}
          </Button>
        </div>
      </form>

      {/* Filters */}
      <Card className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <Filter className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">Filters</span>
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters} className="ml-auto text-xs">
              Clear all
            </Button>
          )}
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Search Mode</label>
            <Select value={mode} onValueChange={setMode}>
              <SelectTrigger className="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="hybrid">Hybrid (Text + Vector)</SelectItem>
                <SelectItem value="text">Text Only (BM25)</SelectItem>
                <SelectItem value="vector">Vector Only (Semantic)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Document Type</label>
            <Select value={docTypeFilter} onValueChange={setDocTypeFilter}>
              <SelectTrigger className="h-9">
                <SelectValue placeholder="All types" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All types</SelectItem>
                <SelectItem value="message">Messages</SelectItem>
                <SelectItem value="conversation">Conversations</SelectItem>
                <SelectItem value="lead_post">Lead Posts</SelectItem>
                <SelectItem value="profile">Profiles</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </Card>

      {/* Results */}
      {error && (
        <Card className="p-6 border-destructive/50 bg-destructive/5">
          <p className="text-destructive text-center">{error}</p>
        </Card>
      )}

      {!hasSearched && !error && (
        <EmptyState
          icon="🔎"
          title="Search your data"
          description="Enter a query above to search across conversations, messages, leads, and profiles."
        />
      )}

      {hasSearched && !loading && !error && results && (
        <>
          {results.hits.length === 0 ? (
            <EmptyState
              icon="🔍"
              title="No results found"
              description={`No documents matching "${query}". Try adjusting your search terms or filters.`}
            />
          ) : (
            <>
              <div className="flex items-center justify-between">
                <p className="text-sm text-muted-foreground">
                  Found {results.total} result{results.total !== 1 ? 's' : ''}
                  {results.max_score && ` (max score: ${results.max_score.toFixed(2)})`}
                </p>
              </div>

              <Card className="overflow-hidden">
                {results.hits.map((hit) => (
                  <SearchResultCard key={hit.id} hit={hit} />
                ))}
              </Card>

              {results.hits.length < results.total && (
                <p className="text-sm text-muted-foreground text-center">
                  Showing {results.hits.length} of {results.total} results
                </p>
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
