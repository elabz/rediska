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
} from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
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

interface ScoutWatchListProps {
  watches: ScoutWatch[];
  onEditWatch: (watch: ScoutWatch) => void;
  onRefresh: () => void;
}

export function ScoutWatchList({ watches, onEditWatch, onRefresh }: ScoutWatchListProps) {
  const [runningWatchId, setRunningWatchId] = useState<number | null>(null);
  const [deletingWatch, setDeletingWatch] = useState<ScoutWatch | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

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
    </>
  );
}
