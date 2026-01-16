'use client';

import { useState, useCallback, useEffect } from 'react';
import Link from 'next/link';
import {
  Loader2,
  Download,
  CheckCircle,
  AlertCircle,
  Clock,
  Database,
  RefreshCw,
  History,
  RotateCcw,
  User,
  MessageSquare,
  ChevronDown,
  ChevronUp,
  Play,
  XCircle,
  Timer,
  Trash2,
  ExternalLink,
  ImageDown,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

// =============================================================================
// Types
// =============================================================================

interface SyncResult {
  status: 'idle' | 'running' | 'success' | 'error';
  message: string;
  details?: {
    conversations_synced?: number;
    messages_synced?: number;
    new_conversations?: number;
    new_messages?: number;
    errors?: string[];
  };
}

interface BackfillResult {
  status: 'idle' | 'running' | 'success' | 'error';
  message: string;
  jobId?: string;
}

interface RedownloadResult {
  status: 'idle' | 'running' | 'success' | 'error';
  message: string;
  jobId?: string;
}

interface JobPayload {
  conversation_id?: number;
  message_id?: number;
  identity_id?: number;
}

interface Job {
  id: number;
  queue_name: string;
  job_type: string;
  status: string;
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
  payload?: JobPayload | null;
}

interface JobCounts {
  queued: number;
  running: number;
  retrying: number;
  failed: number;
  done: number;
  cancelled: number;
  total: number;
}

interface IdentitySyncStatus {
  identity_id: number;
  display_name: string;
  external_username: string;
  provider_id: string;
  last_sync_at: string | null;
  conversations_count: number;
  messages_count: number;
  is_default: boolean;
}

// =============================================================================
// Helper Functions
// =============================================================================

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function getStatusColor(status: string): string {
  switch (status) {
    case 'queued': return 'bg-blue-500/10 text-blue-600 border-blue-500/20';
    case 'running': return 'bg-yellow-500/10 text-yellow-600 border-yellow-500/20';
    case 'retrying': return 'bg-orange-500/10 text-orange-600 border-orange-500/20';
    case 'failed': return 'bg-red-500/10 text-red-600 border-red-500/20';
    case 'done': return 'bg-green-500/10 text-green-600 border-green-500/20';
    case 'cancelled': return 'bg-gray-500/10 text-gray-600 border-gray-500/20';
    default: return 'bg-gray-500/10 text-gray-600 border-gray-500/20';
  }
}

function getStatusIcon(status: string) {
  switch (status) {
    case 'queued': return <Clock className="h-3 w-3" />;
    case 'running': return <Play className="h-3 w-3" />;
    case 'retrying': return <RotateCcw className="h-3 w-3" />;
    case 'failed': return <XCircle className="h-3 w-3" />;
    case 'done': return <CheckCircle className="h-3 w-3" />;
    case 'cancelled': return <XCircle className="h-3 w-3" />;
    default: return <Timer className="h-3 w-3" />;
  }
}

// =============================================================================
// Components
// =============================================================================

function JobRow({
  job,
  onRetry,
  onDelete,
  isDeleting,
}: {
  job: Job;
  onRetry: (id: number) => void;
  onDelete?: (conversationId: number, messageId: number) => void;
  isDeleting?: boolean;
}) {
  const [showError, setShowError] = useState(false);

  const isMessageJob = job.job_type === 'message.send_manual';
  const canDelete = isMessageJob && job.status === 'queued' && job.payload?.conversation_id && job.payload?.message_id && onDelete;
  const hasConversationLink = isMessageJob && job.payload?.conversation_id;

  return (
    <div className="border-b last:border-b-0 px-4 py-3">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <Badge
            variant="outline"
            className={cn("text-xs shrink-0 flex items-center gap-1", getStatusColor(job.status))}
          >
            {getStatusIcon(job.status)}
            {job.status}
          </Badge>
          <span className="font-medium truncate">{job.job_type}</span>
          <span className="text-xs text-muted-foreground shrink-0">#{job.id}</span>
          {hasConversationLink && (
            <Link
              href={`/inbox/${job.payload!.conversation_id}`}
              className="text-xs text-primary hover:underline flex items-center gap-1"
              onClick={(e) => e.stopPropagation()}
            >
              <ExternalLink className="h-3 w-3" />
              View conversation
            </Link>
          )}
        </div>

        <div className="flex items-center gap-4 shrink-0">
          <span className="text-xs text-muted-foreground">
            {job.attempts}/{job.max_attempts} attempts
          </span>
          <span className="text-xs text-muted-foreground">
            {formatDate(job.created_at)}
          </span>
          {canDelete && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onDelete(job.payload!.conversation_id!, job.payload!.message_id!)}
              disabled={isDeleting}
              className="h-7 px-2 text-xs text-destructive hover:text-destructive hover:bg-destructive/10"
            >
              {isDeleting ? (
                <Loader2 className="h-3 w-3 animate-spin mr-1" />
              ) : (
                <Trash2 className="h-3 w-3 mr-1" />
              )}
              Delete
            </Button>
          )}
          {job.status === 'failed' && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onRetry(job.id)}
              className="h-7 px-2 text-xs"
            >
              <RotateCcw className="h-3 w-3 mr-1" />
              Retry
            </Button>
          )}
          {job.last_error && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowError(!showError)}
              className="h-7 px-2"
            >
              {showError ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </Button>
          )}
        </div>
      </div>

      {showError && job.last_error && (
        <div className="mt-2 p-3 rounded bg-red-500/5 border border-red-500/20">
          <pre className="text-xs text-red-600 whitespace-pre-wrap font-mono overflow-x-auto">
            {job.last_error}
          </pre>
        </div>
      )}
    </div>
  );
}

function JobsPanel() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [counts, setCounts] = useState<JobCounts | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<number | null>(null);
  const [deletingMessage, setDeletingMessage] = useState<string | null>(null);

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.append('status', statusFilter);
      params.append('limit', '50');

      const [jobsRes, countsRes] = await Promise.all([
        fetch(`/api/core/ops/jobs?${params.toString()}`, { credentials: 'include' }),
        fetch('/api/core/ops/jobs/counts', { credentials: 'include' }),
      ]);

      if (jobsRes.ok) {
        const data = await jobsRes.json();
        setJobs(data.jobs);
      }

      if (countsRes.ok) {
        const data = await countsRes.json();
        setCounts(data);
      }
    } catch (err) {
      console.error('Failed to fetch jobs:', err);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  const handleRetry = async (jobId: number) => {
    setRetrying(jobId);
    try {
      const response = await fetch(`/api/core/ops/jobs/${jobId}/retry`, {
        method: 'POST',
        credentials: 'include',
      });

      if (response.ok) {
        await fetchJobs();
      }
    } catch (err) {
      console.error('Failed to retry job:', err);
    } finally {
      setRetrying(null);
    }
  };

  const handleDelete = async (conversationId: number, messageId: number) => {
    const key = `${conversationId}-${messageId}`;
    setDeletingMessage(key);
    try {
      const response = await fetch(
        `/api/core/conversations/${conversationId}/messages/${messageId}`,
        {
          method: 'DELETE',
          credentials: 'include',
        }
      );

      if (response.ok) {
        await fetchJobs();
      } else {
        const data = await response.json();
        console.error('Failed to delete message:', data.detail);
      }
    } catch (err) {
      console.error('Failed to delete message:', err);
    } finally {
      setDeletingMessage(null);
    }
  };

  const statusFilters = [
    { key: null, label: 'All', count: counts?.total },
    { key: 'queued', label: 'Queued', count: counts?.queued },
    { key: 'running', label: 'Running', count: counts?.running },
    { key: 'retrying', label: 'Retrying', count: counts?.retrying },
    { key: 'failed', label: 'Failed', count: counts?.failed },
    { key: 'done', label: 'Done', count: counts?.done },
    { key: 'cancelled', label: 'Cancelled', count: counts?.cancelled },
  ];

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-500/10">
              <History className="h-5 w-5 text-purple-500" />
            </div>
            <div>
              <CardTitle className="text-lg">Jobs Monitor</CardTitle>
              <CardDescription>Background job status and history</CardDescription>
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={fetchJobs} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {/* Status Filters */}
        <div className="flex gap-1 mb-4 overflow-x-auto pb-1">
          {statusFilters.map(({ key, label, count }) => (
            <button
              key={label}
              onClick={() => setStatusFilter(key)}
              className={cn(
                "px-3 py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap",
                statusFilter === key
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground"
              )}
            >
              {label}
              {count !== undefined && count > 0 && (
                <span className="ml-1.5 opacity-70">({count})</span>
              )}
            </button>
          ))}
        </div>

        {/* Jobs List */}
        {loading && jobs.length === 0 ? (
          <div className="flex items-center justify-center h-32">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : jobs.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            <History className="h-8 w-8 mx-auto mb-2 opacity-50" />
            <p className="text-sm">No jobs found</p>
          </div>
        ) : (
          <div className="border rounded-lg divide-y max-h-96 overflow-y-auto">
            {jobs.map((job) => (
              <JobRow
                key={job.id}
                job={job}
                onRetry={handleRetry}
                onDelete={handleDelete}
                isDeleting={deletingMessage === `${job.payload?.conversation_id}-${job.payload?.message_id}`}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SyncStatusPanel() {
  const [identities, setIdentities] = useState<IdentitySyncStatus[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/core/ops/sync/status', { credentials: 'include' });
      if (response.ok) {
        const data = await response.json();
        setIdentities(data.identities);
      }
    } catch (err) {
      console.error('Failed to fetch sync status:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-500/10">
              <User className="h-5 w-5 text-green-500" />
            </div>
            <div>
              <CardTitle className="text-lg">Identity Sync Status</CardTitle>
              <CardDescription>Sync statistics per identity</CardDescription>
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={fetchStatus} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {loading && identities.length === 0 ? (
          <div className="flex items-center justify-center h-24">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : identities.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            <User className="h-8 w-8 mx-auto mb-2 opacity-50" />
            <p className="text-sm">No identities found</p>
          </div>
        ) : (
          <div className="space-y-3">
            {identities.map((identity) => (
              <div
                key={identity.identity_id}
                className="p-3 rounded-lg border bg-card"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{identity.display_name}</span>
                    <Badge variant="secondary" className="text-xs">
                      {identity.provider_id}
                    </Badge>
                    {identity.is_default && (
                      <Badge variant="outline" className="text-xs">Default</Badge>
                    )}
                  </div>
                  <span className="text-xs text-muted-foreground">
                    u/{identity.external_username}
                  </span>
                </div>
                <div className="flex items-center gap-4 mt-2 text-sm text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <MessageSquare className="h-3.5 w-3.5" />
                    {identity.conversations_count} conversations
                  </span>
                  <span>{identity.messages_count} messages</span>
                  {identity.last_sync_at && (
                    <span className="flex items-center gap-1">
                      <Clock className="h-3.5 w-3.5" />
                      Last: {formatDate(identity.last_sync_at)}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// =============================================================================
// Main Page
// =============================================================================

export default function OpsPage() {
  const [syncResult, setSyncResult] = useState<SyncResult>({
    status: 'idle',
    message: '',
  });
  const [backfillResult, setBackfillResult] = useState<BackfillResult>({
    status: 'idle',
    message: '',
  });
  const [redownloadResult, setRedownloadResult] = useState<RedownloadResult>({
    status: 'idle',
    message: '',
  });

  const syncMessages = async () => {
    setSyncResult({
      status: 'running',
      message: 'Starting sync...',
    });

    try {
      const response = await fetch('/api/core/conversations/sync', {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to start sync');
      }

      const data = await response.json();
      const jobId = data.job_id;

      setSyncResult({
        status: 'running',
        message: 'Syncing messages from Reddit...',
      });

      // Poll for job completion
      const pollInterval = 2000;
      const maxPolls = 60;
      let polls = 0;

      const checkStatus = async (): Promise<void> => {
        if (polls >= maxPolls) {
          setSyncResult({
            status: 'running',
            message: 'Sync is taking longer than expected. It will continue in the background.',
          });
          return;
        }

        try {
          const statusResponse = await fetch(`/api/core/conversations/sync/${jobId}`, {
            credentials: 'include',
          });

          if (!statusResponse.ok) {
            throw new Error('Failed to check sync status');
          }

          const statusData = await statusResponse.json();

          if (statusData.status === 'success') {
            const result = statusData.result;
            const newCount = (result?.new_conversations || 0) + (result?.new_messages || 0);

            setSyncResult({
              status: 'success',
              message: newCount > 0
                ? `Synced ${result.new_conversations} new conversations and ${result.new_messages} new messages`
                : 'Already up to date',
              details: {
                conversations_synced: result?.conversations_synced,
                messages_synced: result?.messages_synced,
                new_conversations: result?.new_conversations,
                new_messages: result?.new_messages,
                errors: result?.errors,
              },
            });
          } else if (statusData.status === 'failure') {
            setSyncResult({
              status: 'error',
              message: statusData.result?.error || 'Sync failed',
            });
          } else {
            polls++;
            setTimeout(checkStatus, pollInterval);
          }
        } catch {
          setSyncResult({
            status: 'error',
            message: 'Failed to check sync status',
          });
        }
      };

      setTimeout(checkStatus, pollInterval);
    } catch (err) {
      setSyncResult({
        status: 'error',
        message: err instanceof Error ? err.message : 'Sync failed',
      });
    }
  };

  const triggerBackfill = async () => {
    setBackfillResult({
      status: 'running',
      message: 'Starting full backfill...',
    });

    try {
      const response = await fetch('/api/core/ops/backfill/conversations', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to start backfill');
      }

      const data = await response.json();
      const jobId = data.job_id;

      setBackfillResult({
        status: 'running',
        message: 'Backfilling conversation history...',
        jobId,
      });

      // Poll for job completion
      const pollInterval = 3000;
      const maxPolls = 120;
      let polls = 0;

      const checkStatus = async (): Promise<void> => {
        if (polls >= maxPolls) {
          setBackfillResult({
            status: 'running',
            message: 'Backfill is taking longer than expected. It will continue in the background.',
            jobId,
          });
          return;
        }

        try {
          const statusResponse = await fetch(`/api/core/ops/backfill/${jobId}`, {
            credentials: 'include',
          });

          if (!statusResponse.ok) {
            throw new Error('Failed to check backfill status');
          }

          const statusData = await statusResponse.json();

          if (statusData.status === 'success') {
            const result = statusData.result;
            setBackfillResult({
              status: 'success',
              message: `Backfill complete. ${result?.new_conversations || 0} new conversations, ${result?.new_messages || 0} new messages.`,
              jobId,
            });
          } else if (statusData.status === 'failure') {
            setBackfillResult({
              status: 'error',
              message: statusData.result?.error || 'Backfill failed',
              jobId,
            });
          } else {
            polls++;
            setTimeout(checkStatus, pollInterval);
          }
        } catch {
          setBackfillResult({
            status: 'error',
            message: 'Failed to check backfill status',
            jobId,
          });
        }
      };

      setTimeout(checkStatus, pollInterval);
    } catch (err) {
      setBackfillResult({
        status: 'error',
        message: err instanceof Error ? err.message : 'Backfill failed',
      });
    }
  };

  const triggerRedownload = async () => {
    setRedownloadResult({
      status: 'running',
      message: 'Starting attachment redownload...',
    });

    try {
      const response = await fetch('/api/core/ops/redownload/attachments', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit: 500 }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to start redownload');
      }

      const data = await response.json();
      const jobId = data.job_id;

      setRedownloadResult({
        status: 'running',
        message: 'Re-downloading missing images from messages...',
        jobId,
      });

      // Poll for job completion
      const pollInterval = 2000;
      const maxPolls = 120;
      let polls = 0;

      const checkStatus = async (): Promise<void> => {
        if (polls >= maxPolls) {
          setRedownloadResult({
            status: 'running',
            message: 'Redownload is taking longer than expected. It will continue in the background.',
            jobId,
          });
          return;
        }

        try {
          const statusResponse = await fetch(`/api/core/ops/backfill/${jobId}`, {
            credentials: 'include',
          });

          if (!statusResponse.ok) {
            throw new Error('Failed to check redownload status');
          }

          const statusData = await statusResponse.json();

          if (statusData.status === 'success') {
            const result = statusData.result;
            setRedownloadResult({
              status: 'success',
              message: `Downloaded ${result?.downloaded || 0} attachments (${result?.skipped || 0} already existed, ${result?.failed || 0} failed)`,
              jobId,
            });
          } else if (statusData.status === 'failure') {
            setRedownloadResult({
              status: 'error',
              message: statusData.result?.error || 'Redownload failed',
              jobId,
            });
          } else {
            polls++;
            setTimeout(checkStatus, pollInterval);
          }
        } catch {
          setRedownloadResult({
            status: 'error',
            message: 'Failed to check redownload status',
            jobId,
          });
        }
      };

      setTimeout(checkStatus, pollInterval);
    } catch (err) {
      setRedownloadResult({
        status: 'error',
        message: err instanceof Error ? err.message : 'Redownload failed',
      });
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Operations</h1>
        <p className="text-muted-foreground mt-1">
          Manage sync operations, monitor jobs, and view system status
        </p>
      </div>

      {/* Sync & Backfill Row */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Reddit Sync Card */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-orange-500/10">
                <Database className="h-5 w-5 text-orange-500" />
              </div>
              <div>
                <CardTitle className="text-lg">Reddit Sync</CardTitle>
                <CardDescription>Import recent messages</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Fetch your latest conversations and messages from Reddit. This will import
              recent inbox and sent messages.
            </p>

            <Button
              onClick={syncMessages}
              disabled={syncResult.status === 'running'}
              className="w-full"
              size="lg"
            >
              {syncResult.status === 'running' ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Syncing...
                </>
              ) : (
                <>
                  <Download className="h-4 w-4 mr-2" />
                  Sync from Reddit
                </>
              )}
            </Button>

            {syncResult.status !== 'idle' && (
              <div className={cn(
                "rounded-lg p-4",
                syncResult.status === 'running'
                  ? 'bg-blue-500/10 border border-blue-500/20'
                  : syncResult.status === 'success'
                    ? 'bg-emerald-500/10 border border-emerald-500/20'
                    : 'bg-destructive/10 border border-destructive/20'
              )}>
                <div className="flex items-start gap-3">
                  {syncResult.status === 'running' && (
                    <Clock className="h-5 w-5 text-blue-500 shrink-0 mt-0.5" />
                  )}
                  {syncResult.status === 'success' && (
                    <CheckCircle className="h-5 w-5 text-emerald-500 shrink-0 mt-0.5" />
                  )}
                  {syncResult.status === 'error' && (
                    <AlertCircle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
                  )}
                  <div className="space-y-1 min-w-0">
                    <p className={cn(
                      "text-sm font-medium",
                      syncResult.status === 'running'
                        ? 'text-blue-600 dark:text-blue-400'
                        : syncResult.status === 'success'
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : 'text-destructive'
                    )}>
                      {syncResult.message}
                    </p>
                    {syncResult.details && syncResult.status === 'success' && (
                      <div className="flex flex-wrap gap-2 mt-2">
                        <Badge variant="outline" className="text-xs">
                          {syncResult.details.conversations_synced || 0} conversations
                        </Badge>
                        <Badge variant="outline" className="text-xs">
                          {syncResult.details.messages_synced || 0} messages
                        </Badge>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Backfill Card */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/10">
                <History className="h-5 w-5 text-blue-500" />
              </div>
              <div>
                <CardTitle className="text-lg">Full Backfill</CardTitle>
                <CardDescription>Import complete history</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Import your complete conversation history from Reddit. Use this for initial
              setup or to recover missing messages.
            </p>

            <Button
              onClick={triggerBackfill}
              disabled={backfillResult.status === 'running'}
              className="w-full"
              size="lg"
              variant="secondary"
            >
              {backfillResult.status === 'running' ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Backfilling...
                </>
              ) : (
                <>
                  <History className="h-4 w-4 mr-2" />
                  Start Full Backfill
                </>
              )}
            </Button>

            {backfillResult.status !== 'idle' && (
              <div className={cn(
                "rounded-lg p-4",
                backfillResult.status === 'running'
                  ? 'bg-blue-500/10 border border-blue-500/20'
                  : backfillResult.status === 'success'
                    ? 'bg-emerald-500/10 border border-emerald-500/20'
                    : 'bg-destructive/10 border border-destructive/20'
              )}>
                <div className="flex items-start gap-3">
                  {backfillResult.status === 'running' && (
                    <Clock className="h-5 w-5 text-blue-500 shrink-0 mt-0.5" />
                  )}
                  {backfillResult.status === 'success' && (
                    <CheckCircle className="h-5 w-5 text-emerald-500 shrink-0 mt-0.5" />
                  )}
                  {backfillResult.status === 'error' && (
                    <AlertCircle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
                  )}
                  <div className="space-y-1 min-w-0">
                    <p className={cn(
                      "text-sm font-medium",
                      backfillResult.status === 'running'
                        ? 'text-blue-600 dark:text-blue-400'
                        : backfillResult.status === 'success'
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : 'text-destructive'
                    )}>
                      {backfillResult.message}
                    </p>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Re-download Attachments Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-pink-500/10">
              <ImageDown className="h-5 w-5 text-pink-500" />
            </div>
            <div>
              <CardTitle className="text-lg">Re-download Attachments</CardTitle>
              <CardDescription>Recover missing images from messages</CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Scan all messages for image URLs and download any that are missing locally.
            This extracts URLs from already-downloaded messages - no Reddit API calls needed.
          </p>

          <Button
            onClick={triggerRedownload}
            disabled={redownloadResult.status === 'running'}
            className="w-full"
            size="lg"
            variant="secondary"
          >
            {redownloadResult.status === 'running' ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
                Downloading...
              </>
            ) : (
              <>
                <ImageDown className="h-4 w-4 mr-2" />
                Re-download Missing Images
              </>
            )}
          </Button>

          {redownloadResult.status !== 'idle' && (
            <div className={cn(
              "rounded-lg p-4",
              redownloadResult.status === 'running'
                ? 'bg-blue-500/10 border border-blue-500/20'
                : redownloadResult.status === 'success'
                  ? 'bg-emerald-500/10 border border-emerald-500/20'
                  : 'bg-destructive/10 border border-destructive/20'
            )}>
              <div className="flex items-start gap-3">
                {redownloadResult.status === 'running' && (
                  <Clock className="h-5 w-5 text-blue-500 shrink-0 mt-0.5" />
                )}
                {redownloadResult.status === 'success' && (
                  <CheckCircle className="h-5 w-5 text-emerald-500 shrink-0 mt-0.5" />
                )}
                {redownloadResult.status === 'error' && (
                  <AlertCircle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
                )}
                <div className="space-y-1 min-w-0">
                  <p className={cn(
                    "text-sm font-medium",
                    redownloadResult.status === 'running'
                      ? 'text-blue-600 dark:text-blue-400'
                      : redownloadResult.status === 'success'
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : 'text-destructive'
                  )}>
                    {redownloadResult.message}
                  </p>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Sync Status Panel */}
      <SyncStatusPanel />

      {/* Jobs Panel */}
      <JobsPanel />
    </div>
  );
}
