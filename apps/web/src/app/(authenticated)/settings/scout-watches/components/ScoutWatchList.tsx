'use client';

import { useState } from 'react';
import {
  Eye,
  EyeOff,
  Play,
  Pencil,
  Trash2,
  Clock,
  Users,
  FileText,
  MoreHorizontal,
  Loader2,
  History,
  ExternalLink,
  CheckCircle,
  XCircle,
  AlertCircle,
} from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { ScoutWatch } from '../page';

interface ScoutWatchRun {
  id: number;
  watch_id: number;
  started_at: string;
  completed_at: string | null;
  status: string;
  posts_fetched: number;
  posts_new: number;
  posts_analyzed: number;
  leads_created: number;
  error_message: string | null;
  search_url: string | null;
}

interface ScoutWatchPost {
  id: number;
  watch_id: number;
  external_post_id: string;
  post_title: string | null;
  post_author: string | null;
  first_seen_at: string;
  run_id: number | null;
  analysis_status: string;
  analysis_recommendation: string | null;
  analysis_confidence: number | null;
  analysis_reasoning: string | null;
  lead_id: number | null;
}

interface RunDetailResponse {
  run: ScoutWatchRun;
  posts: ScoutWatchPost[];
}

interface ScoutWatchListProps {
  watches: ScoutWatch[];
  onEditWatch: (watch: ScoutWatch) => void;
  onRefresh: () => void;
}

export function ScoutWatchList({ watches, onEditWatch, onRefresh }: ScoutWatchListProps) {
  const [runningWatchId, setRunningWatchId] = useState<number | null>(null);
  const [deletingWatch, setDeletingWatch] = useState<ScoutWatch | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // Run history state
  const [historyWatch, setHistoryWatch] = useState<ScoutWatch | null>(null);
  const [runs, setRuns] = useState<ScoutWatchRun[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [selectedRunDetail, setSelectedRunDetail] = useState<RunDetailResponse | null>(null);
  const [loadingRunDetail, setLoadingRunDetail] = useState(false);
  const [expandedPostId, setExpandedPostId] = useState<number | null>(null);

  const handleRunWatch = async (watchId: number) => {
    setRunningWatchId(watchId);
    try {
      const response = await fetch(`/api/core/scout-watches/${watchId}/run`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to trigger watch run');
      }

      // Refresh the list after a short delay to show updated stats
      setTimeout(onRefresh, 2000);
    } catch (err) {
      console.error('Run watch error:', err);
    } finally {
      setRunningWatchId(null);
    }
  };

  const handleToggleActive = async (watch: ScoutWatch) => {
    try {
      const response = await fetch(`/api/core/scout-watches/${watch.id}`, {
        method: 'PUT',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ is_active: !watch.is_active }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to update watch');
      }

      onRefresh();
    } catch (err) {
      console.error('Toggle active error:', err);
    }
  };

  const handleDeleteWatch = async () => {
    if (!deletingWatch) return;

    setIsDeleting(true);
    try {
      const response = await fetch(`/api/core/scout-watches/${deletingWatch.id}`, {
        method: 'DELETE',
        credentials: 'include',
      });

      if (!response.ok && response.status !== 204) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to delete watch');
      }

      onRefresh();
    } catch (err) {
      console.error('Delete watch error:', err);
    } finally {
      setIsDeleting(false);
      setDeletingWatch(null);
    }
  };

  const handleViewHistory = async (watch: ScoutWatch) => {
    setHistoryWatch(watch);
    setRuns([]);
    setSelectedRunDetail(null);
    setLoadingRuns(true);

    try {
      const response = await fetch(`/api/core/scout-watches/${watch.id}/runs?limit=20`, {
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error('Failed to fetch run history');
      }

      const data = await response.json();
      setRuns(data.runs || []);
    } catch (err) {
      console.error('Fetch run history error:', err);
    } finally {
      setLoadingRuns(false);
    }
  };

  const handleViewRunDetail = async (watchId: number, runId: number) => {
    setLoadingRunDetail(true);
    setSelectedRunDetail(null);

    try {
      const response = await fetch(`/api/core/scout-watches/${watchId}/runs/${runId}`, {
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error('Failed to fetch run details');
      }

      const data = await response.json();
      setSelectedRunDetail(data);
    } catch (err) {
      console.error('Fetch run detail error:', err);
    } finally {
      setLoadingRunDetail(false);
    }
  };

  const getRecommendationIcon = (recommendation: string | null) => {
    switch (recommendation) {
      case 'suitable':
        return <CheckCircle className="h-4 w-4 text-green-500" />;
      case 'not_suitable':
        return <XCircle className="h-4 w-4 text-red-500" />;
      case 'needs_review':
        return <AlertCircle className="h-4 w-4 text-yellow-500" />;
      default:
        return <AlertCircle className="h-4 w-4 text-muted-foreground" />;
    }
  };

  const getRecommendationLabel = (recommendation: string | null) => {
    switch (recommendation) {
      case 'suitable':
        return 'Suitable';
      case 'not_suitable':
        return 'Not Suitable';
      case 'needs_review':
        return 'Needs Review';
      default:
        return 'Pending';
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'Never';
    // Ensure UTC interpretation by appending 'Z' if not present
    const utcDateStr = dateStr.endsWith('Z') ? dateStr : dateStr + 'Z';
    const date = new Date(utcDateStr);
    return date.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (watches.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12">
          <Eye className="h-12 w-12 text-muted-foreground/50 mb-4" />
          <h3 className="text-lg font-medium mb-2">No Scout Watches</h3>
          <p className="text-muted-foreground text-sm text-center max-w-md">
            Create your first scout watch to automatically monitor subreddits
            and discover new leads.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <>
      <div className="space-y-3">
        {watches.map((watch) => (
          <Card key={watch.id} className={!watch.is_active ? 'opacity-60' : ''}>
            <CardContent className="p-4">
              <div className="flex items-start justify-between gap-4">
                {/* Watch Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="font-medium truncate">{watch.source_location}</h3>
                    <Badge variant={watch.is_active ? 'default' : 'secondary'}>
                      {watch.is_active ? 'Active' : 'Paused'}
                    </Badge>
                    {watch.auto_analyze && (
                      <Badge variant="outline">Auto-analyze</Badge>
                    )}
                  </div>

                  {watch.search_query && (
                    <p className="text-sm text-muted-foreground mb-2 truncate">
                      Search: {watch.search_query}
                    </p>
                  )}

                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <FileText className="h-3 w-3" />
                      {watch.total_posts_seen} seen
                    </span>
                    <span className="flex items-center gap-1">
                      <Users className="h-3 w-3" />
                      {watch.total_leads_created} leads
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      Last run: {formatDate(watch.last_run_at)}
                    </span>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleRunWatch(watch.id)}
                    disabled={runningWatchId === watch.id || !watch.is_active}
                  >
                    {runningWatchId === watch.id ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Play className="h-4 w-4" />
                    )}
                    <span className="ml-1 hidden sm:inline">Run Now</span>
                  </Button>

                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon">
                        <MoreHorizontal className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onClick={() => handleViewHistory(watch)}>
                        <History className="h-4 w-4 mr-2" />
                        Run History
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onClick={() => onEditWatch(watch)}>
                        <Pencil className="h-4 w-4 mr-2" />
                        Edit
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => handleToggleActive(watch)}>
                        {watch.is_active ? (
                          <>
                            <EyeOff className="h-4 w-4 mr-2" />
                            Pause
                          </>
                        ) : (
                          <>
                            <Eye className="h-4 w-4 mr-2" />
                            Activate
                          </>
                        )}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        onClick={() => setDeletingWatch(watch)}
                        className="text-destructive focus:text-destructive"
                      >
                        <Trash2 className="h-4 w-4 mr-2" />
                        Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={!!deletingWatch} onOpenChange={() => setDeletingWatch(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Scout Watch</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete the watch for{' '}
              <strong>{deletingWatch?.source_location}</strong>? This action cannot be undone.
              Existing leads created by this watch will not be affected.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isDeleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteWatch}
              disabled={isDeleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isDeleting ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : null}
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Run History Dialog */}
      <Dialog open={!!historyWatch} onOpenChange={() => {
        setHistoryWatch(null);
        setSelectedRunDetail(null);
      }}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              Run History: {historyWatch?.source_location}
            </DialogTitle>
            <DialogDescription>
              {historyWatch?.search_query && `Search: ${historyWatch.search_query}`}
            </DialogDescription>
          </DialogHeader>

          {loadingRuns ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : runs.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No runs yet. Click "Run Now" to trigger a watch run.
            </div>
          ) : (
            <div className="space-y-3">
              {runs.map((run) => (
                <Card key={run.id} className={run.status === 'failed' ? 'border-destructive/50' : ''}>
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-2">
                          <Badge variant={run.status === 'completed' ? 'default' : run.status === 'failed' ? 'destructive' : 'secondary'}>
                            {run.status}
                          </Badge>
                          <span className="text-sm text-muted-foreground">
                            {formatDate(run.started_at)}
                          </span>
                        </div>

                        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                          <span>{run.posts_fetched} fetched</span>
                          <span>{run.posts_new} new</span>
                          <span>{run.posts_analyzed} analyzed</span>
                          <span className="font-medium">{run.leads_created} leads</span>
                        </div>

                        {run.error_message && (
                          <p className="text-sm text-destructive mt-2 truncate">
                            {run.error_message}
                          </p>
                        )}

                        {run.search_url && (
                          <div className="mt-2">
                            <a
                              href={run.search_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-xs text-blue-500 hover:underline flex items-center gap-1"
                            >
                              <ExternalLink className="h-3 w-3" />
                              View Reddit Search URL
                            </a>
                          </div>
                        )}
                      </div>

                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleViewRunDetail(run.watch_id, run.id)}
                        disabled={loadingRunDetail}
                      >
                        {loadingRunDetail && selectedRunDetail?.run.id === run.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          'View Posts'
                        )}
                      </Button>
                    </div>

                    {/* Expanded Run Detail */}
                    {selectedRunDetail?.run.id === run.id && (
                      <div className="mt-4 pt-4 border-t">
                        {selectedRunDetail.posts.length === 0 ? (
                          <p className="text-sm text-muted-foreground">No posts in this run.</p>
                        ) : (
                          <div className="space-y-2">
                            <h4 className="text-sm font-medium mb-2">
                              Posts ({selectedRunDetail.posts.length})
                            </h4>
                            {selectedRunDetail.posts.map((post) => (
                              <Collapsible
                                key={post.id}
                                open={expandedPostId === post.id}
                                onOpenChange={(open) => setExpandedPostId(open ? post.id : null)}
                              >
                                <div className="border rounded-lg p-3">
                                  <CollapsibleTrigger asChild>
                                    <div className="flex items-start gap-3 cursor-pointer">
                                      {getRecommendationIcon(post.analysis_recommendation)}
                                      <div className="flex-1 min-w-0">
                                        <p className="text-sm font-medium truncate">
                                          {post.post_title || post.external_post_id}
                                        </p>
                                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                                          {post.post_author && <span>u/{post.post_author}</span>}
                                          <span>{getRecommendationLabel(post.analysis_recommendation)}</span>
                                          {post.analysis_confidence !== null && (
                                            <span>({Math.round(post.analysis_confidence * 100)}% confidence)</span>
                                          )}
                                          {post.lead_id && (
                                            <Badge variant="outline" className="text-xs">
                                              Lead #{post.lead_id}
                                            </Badge>
                                          )}
                                        </div>
                                      </div>
                                    </div>
                                  </CollapsibleTrigger>
                                  <CollapsibleContent>
                                    {post.analysis_reasoning && (
                                      <div className="mt-3 pt-3 border-t">
                                        <h5 className="text-xs font-medium text-muted-foreground mb-1">
                                          Analysis Reasoning:
                                        </h5>
                                        <p className="text-sm whitespace-pre-wrap">
                                          {post.analysis_reasoning}
                                        </p>
                                      </div>
                                    )}
                                    <div className="mt-2 flex gap-2">
                                      <a
                                        href={`https://reddit.com/comments/${post.external_post_id}`}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="text-xs text-blue-500 hover:underline flex items-center gap-1"
                                      >
                                        <ExternalLink className="h-3 w-3" />
                                        View on Reddit
                                      </a>
                                    </div>
                                  </CollapsibleContent>
                                </div>
                              </Collapsible>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
