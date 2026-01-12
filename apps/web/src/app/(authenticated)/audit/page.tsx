'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';
import { Loader2, RefreshCw, Filter, ChevronDown, AlertCircle, CheckCircle, Clock, User, Bot, Settings } from 'lucide-react';
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
import { IdentityBadge } from '@/components/identity';
import { useIdentities } from '@/hooks/useIdentities';

interface AuditEntry {
  id: number;
  ts: string;
  actor: 'user' | 'system' | 'agent';
  action_type: string;
  provider_id: string | null;
  identity_id: number | null;
  entity_type: string | null;
  entity_id: number | null;
  request_json: Record<string, unknown> | null;
  response_json: Record<string, unknown> | null;
  result: 'ok' | 'error';
  error_detail: string | null;
}

interface AuditResponse {
  entries: AuditEntry[];
  total: number;
  next_cursor: string | null;
}

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatRelativeTime(dateString: string): string {
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

function ActorIcon({ actor }: { actor: string }) {
  switch (actor) {
    case 'user':
      return <User className="h-4 w-4" />;
    case 'system':
      return <Settings className="h-4 w-4" />;
    case 'agent':
      return <Bot className="h-4 w-4" />;
    default:
      return <User className="h-4 w-4" />;
  }
}

function AuditEntryCard({ entry, identity }: { entry: AuditEntry; identity?: { provider_id: string; display_name: string; external_username: string } }) {
  const [isOpen, setIsOpen] = useState(false);

  const hasDetails = entry.request_json || entry.response_json || entry.error_detail;

  return (
    <div className="border-b border-border last:border-b-0">
      <button
        className="w-full p-4 text-left hover:bg-muted/50 transition-colors"
        onClick={() => hasDetails && setIsOpen(!isOpen)}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 min-w-0">
            <div className={`mt-0.5 p-1.5 rounded-full ${
              entry.result === 'ok' ? 'bg-emerald-500/10 text-emerald-600' : 'bg-destructive/10 text-destructive'
            }`}>
              {entry.result === 'ok' ? (
                <CheckCircle className="h-4 w-4" />
              ) : (
                <AlertCircle className="h-4 w-4" />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium">{entry.action_type}</span>
                <Badge variant="outline" className="text-xs flex items-center gap-1">
                  <ActorIcon actor={entry.actor} />
                  {entry.actor}
                </Badge>
                {entry.provider_id && (
                  <Badge variant="secondary" className="text-xs">
                    {entry.provider_id}
                  </Badge>
                )}
                {identity && (
                  <IdentityBadge identity={identity} size="sm" />
                )}
              </div>
              <div className="flex items-center gap-2 mt-1 text-sm text-muted-foreground">
                <Clock className="h-3 w-3" />
                <span title={formatDate(entry.ts)}>{formatRelativeTime(entry.ts)}</span>
                {entry.entity_type && (
                  <span>
                    {entry.entity_type}
                    {entry.entity_id && ` #${entry.entity_id}`}
                  </span>
                )}
              </div>
              {entry.error_detail && !isOpen && (
                <p className="text-sm text-destructive mt-1 truncate">
                  {entry.error_detail}
                </p>
              )}
            </div>
          </div>
          {hasDetails && (
            <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform shrink-0 ${isOpen ? 'rotate-180' : ''}`} />
          )}
        </div>
      </button>
      {hasDetails && isOpen && (
        <div className="px-4 pb-4 space-y-3">
          {entry.error_detail && (
            <div className="p-3 bg-destructive/10 rounded-lg">
              <h4 className="text-xs font-medium text-destructive mb-1">Error Details</h4>
              <pre className="text-xs text-destructive whitespace-pre-wrap break-words">
                {entry.error_detail}
              </pre>
            </div>
          )}
          {entry.request_json && Object.keys(entry.request_json).length > 0 && (
            <div className="p-3 bg-muted rounded-lg">
              <h4 className="text-xs font-medium text-muted-foreground mb-1">Request</h4>
              <pre className="text-xs whitespace-pre-wrap break-words overflow-x-auto">
                {JSON.stringify(entry.request_json, null, 2)}
              </pre>
            </div>
          )}
          {entry.response_json && Object.keys(entry.response_json).length > 0 && (
            <div className="p-3 bg-muted rounded-lg">
              <h4 className="text-xs font-medium text-muted-foreground mb-1">Response</h4>
              <pre className="text-xs whitespace-pre-wrap break-words overflow-x-auto">
                {JSON.stringify(entry.response_json, null, 2)}
              </pre>
            </div>
          )}
          <div className="text-xs text-muted-foreground">
            ID: {entry.id} | {formatDate(entry.ts)}
          </div>
        </div>
      )}
    </div>
  );
}

export default function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [total, setTotal] = useState(0);

  // Filters
  const [actionType, setActionType] = useState<string>('');
  const [actor, setActor] = useState<string>('all');
  const [result, setResult] = useState<string>('all');
  const [identityFilter, setIdentityFilter] = useState<string>('all');

  const { identities } = useIdentities();

  // Build identity lookup map
  const identityMap = useMemo(() => {
    const map: Record<number, typeof identities[0]> = {};
    identities.forEach(i => { map[i.id] = i; });
    return map;
  }, [identities]);

  const fetchAuditLogs = useCallback(async (cursor?: string, append = false) => {
    if (!append) {
      setLoading(true);
    } else {
      setLoadingMore(true);
    }
    setError(null);

    try {
      const params = new URLSearchParams({ limit: '50' });
      if (cursor) params.set('cursor', cursor);
      if (actionType) params.set('action_type', actionType);
      if (actor && actor !== 'all') params.set('actor', actor);
      if (result && result !== 'all') params.set('result', result);
      if (identityFilter && identityFilter !== 'all') params.set('identity_id', identityFilter);

      const response = await fetch(`/api/core/audit?${params.toString()}`, {
        credentials: 'include',
      });

      if (!response.ok) {
        if (response.status === 401) {
          throw new Error('Please log in to view audit logs');
        }
        const data = await response.json();
        throw new Error(data.detail || 'Failed to load audit logs');
      }

      const data: AuditResponse = await response.json();

      if (append) {
        setEntries(prev => [...prev, ...data.entries]);
      } else {
        setEntries(data.entries);
      }
      setNextCursor(data.next_cursor);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [actionType, actor, result, identityFilter]);

  useEffect(() => {
    fetchAuditLogs();
  }, [fetchAuditLogs]);

  const loadMore = () => {
    if (nextCursor && !loadingMore) {
      fetchAuditLogs(nextCursor, true);
    }
  };

  const refresh = () => {
    fetchAuditLogs();
  };

  const clearFilters = () => {
    setActionType('');
    setActor('all');
    setResult('all');
    setIdentityFilter('all');
  };

  const hasFilters = actionType || (actor && actor !== 'all') || (result && result !== 'all') || (identityFilter && identityFilter !== 'all');

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

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Audit Log</h1>
          <p className="text-muted-foreground mt-1">
            {total} total entries
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
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Action Type</label>
            <Input
              placeholder="e.g., auth.login"
              value={actionType}
              onChange={(e) => setActionType(e.target.value)}
              className="h-9"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Actor</label>
            <Select value={actor} onValueChange={setActor}>
              <SelectTrigger className="h-9">
                <SelectValue placeholder="All actors" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All actors</SelectItem>
                <SelectItem value="user">User</SelectItem>
                <SelectItem value="system">System</SelectItem>
                <SelectItem value="agent">Agent</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Result</label>
            <Select value={result} onValueChange={setResult}>
              <SelectTrigger className="h-9">
                <SelectValue placeholder="All results" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All results</SelectItem>
                <SelectItem value="ok">Success</SelectItem>
                <SelectItem value="error">Error</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {identities.length > 1 && (
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Identity</label>
              <Select value={identityFilter} onValueChange={setIdentityFilter}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="All identities" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All identities</SelectItem>
                  {identities.map((identity) => (
                    <SelectItem key={identity.id} value={String(identity.id)}>
                      {identity.display_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>
      </Card>

      {/* Entries */}
      {entries.length === 0 ? (
        <EmptyState
          icon="📋"
          title="No audit entries"
          description={hasFilters ? "No entries match your filters. Try adjusting your search criteria." : "System actions will appear here as they occur."}
        />
      ) : (
        <>
          <Card className="overflow-hidden">
            {entries.map((entry) => (
              <AuditEntryCard
                key={entry.id}
                entry={entry}
                identity={entry.identity_id ? identityMap[entry.identity_id] : undefined}
              />
            ))}
          </Card>

          {nextCursor && (
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

          <p className="text-sm text-muted-foreground text-center">
            Showing {entries.length} of {total} entries
          </p>
        </>
      )}
    </div>
  );
}
