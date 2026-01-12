'use client';

import { useState } from 'react';
import { Loader2, Download, CheckCircle, AlertCircle, Clock, Database, RefreshCw } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

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

export default function OpsPage() {
  const [syncResult, setSyncResult] = useState<SyncResult>({
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
      const maxPolls = 60; // Max 2 minutes
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

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Operations</h1>
        <p className="text-muted-foreground mt-1">
          Manage sync operations and monitor system status
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Reddit Sync Card */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-orange-500/10">
                  <Database className="h-5 w-5 text-orange-500" />
                </div>
                <div>
                  <CardTitle className="text-lg">Reddit Sync</CardTitle>
                  <CardDescription>Import messages from Reddit</CardDescription>
                </div>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Fetch your latest conversations and messages from Reddit. This will import
              both inbox and sent messages.
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

            {/* Status Display */}
            {syncResult.status !== 'idle' && (
              <div className={`rounded-lg p-4 ${
                syncResult.status === 'running'
                  ? 'bg-blue-500/10 border border-blue-500/20'
                  : syncResult.status === 'success'
                    ? 'bg-emerald-500/10 border border-emerald-500/20'
                    : 'bg-destructive/10 border border-destructive/20'
              }`}>
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
                    <p className={`text-sm font-medium ${
                      syncResult.status === 'running'
                        ? 'text-blue-600 dark:text-blue-400'
                        : syncResult.status === 'success'
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : 'text-destructive'
                    }`}>
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
                    {syncResult.details?.errors && syncResult.details.errors.length > 0 && (
                      <p className="text-xs text-muted-foreground mt-2">
                        {syncResult.details.errors.length} warning(s) during sync
                      </p>
                    )}
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Placeholder for future operations */}
        <Card className="opacity-60">
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
                <RefreshCw className="h-5 w-5 text-muted-foreground" />
              </div>
              <div>
                <CardTitle className="text-lg">Auto-Sync</CardTitle>
                <CardDescription>Scheduled background sync</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Automatic message sync will be available in a future update.
            </p>
            <Badge variant="secondary" className="mt-4">Coming Soon</Badge>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
