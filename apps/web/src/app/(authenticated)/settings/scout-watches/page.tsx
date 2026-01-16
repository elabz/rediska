'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Loader2,
  AlertCircle,
  Eye,
  Plus,
  RefreshCw,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

import { ScoutWatchList } from './components/ScoutWatchList';
import { ScoutWatchEditor } from './components/ScoutWatchEditor';

// Types
export interface ScoutWatch {
  id: number;
  provider_id: string;
  source_location: string;
  search_query: string | null;
  sort_by: string;
  time_filter: string;
  identity_id: number | null;
  is_active: boolean;
  auto_analyze: boolean;
  min_confidence: number;
  total_posts_seen: number;
  total_matches: number;
  total_leads_created: number;
  last_run_at: string | null;
  last_match_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScoutWatchesResponse {
  watches: ScoutWatch[];
}

export default function ScoutWatchesSettingsPage() {
  const [watches, setWatches] = useState<ScoutWatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingWatch, setEditingWatch] = useState<ScoutWatch | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  const fetchWatches = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/core/scout-watches', {
        credentials: 'include',
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to fetch scout watches');
      }

      const data: ScoutWatchesResponse = await response.json();
      setWatches(data.watches);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchWatches();
  }, [fetchWatches]);

  const handleWatchUpdated = () => {
    fetchWatches();
    setEditingWatch(null);
    setIsCreating(false);
  };

  const handleCreateNew = () => {
    setEditingWatch(null);
    setIsCreating(true);
  };

  if (loading) {
    return (
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-6xl mx-auto">
        <Card className="p-8">
          <div className="text-center">
            <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
            <p className="text-destructive font-medium">{error}</p>
            <Button variant="outline" onClick={fetchWatches} className="mt-4">
              Try Again
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/10">
            <Eye className="h-5 w-5 text-blue-500" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">Scout Watches</h1>
            <p className="text-muted-foreground">
              Automatic subreddit monitoring for lead discovery
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={fetchWatches}>
            <RefreshCw className="h-4 w-4 mr-1" />
            Refresh
          </Button>
          <Button size="sm" onClick={handleCreateNew}>
            <Plus className="h-4 w-4 mr-1" />
            New Watch
          </Button>
        </div>
      </div>

      {/* Description Card */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">About Scout Watches</CardTitle>
        </CardHeader>
        <CardContent>
          <CardDescription className="text-sm">
            Scout watches automatically monitor subreddits for new posts matching your criteria.
            Every 5 minutes, new posts are fetched, analyzed using the Meta-Analysis agent,
            and matching posts are automatically added to your Leads. Configure search queries,
            sort order, and confidence thresholds for each watch.
          </CardDescription>
        </CardContent>
      </Card>

      {/* Watch List or Editor */}
      {editingWatch || isCreating ? (
        <ScoutWatchEditor
          watch={editingWatch}
          onClose={() => {
            setEditingWatch(null);
            setIsCreating(false);
          }}
          onSaved={handleWatchUpdated}
        />
      ) : (
        <ScoutWatchList
          watches={watches}
          onEditWatch={setEditingWatch}
          onRefresh={fetchWatches}
        />
      )}
    </div>
  );
}
