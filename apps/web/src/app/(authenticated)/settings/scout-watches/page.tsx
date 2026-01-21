'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Loader2,
  AlertCircle,
  Eye,
  Plus,
  RefreshCw,
  HelpCircle,
  ChevronDown,
  ChevronUp,
  Search,
  FileText,
  Brain,
  Users,
  Heart,
  AlertTriangle,
  Sparkles,
  CheckCircle2,
  ArrowRight,
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
  const [showHelp, setShowHelp] = useState(false);

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

      {/* How It Works - Collapsible Help Section */}
      <Card>
        <CardHeader className="pb-3">
          <button
            onClick={() => setShowHelp(!showHelp)}
            className="flex items-center justify-between w-full text-left"
          >
            <div className="flex items-center gap-2">
              <HelpCircle className="h-5 w-5 text-blue-500" />
              <CardTitle className="text-base">How Scout Watch Works</CardTitle>
            </div>
            {showHelp ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
          </button>
        </CardHeader>
        {showHelp && (
          <CardContent className="pt-0 space-y-6">
            {/* Overview */}
            <div className="text-sm text-muted-foreground">
              Scout Watch automatically monitors subreddits for potential leads using AI-powered
              multi-agent analysis. When a post meets your criteria, it becomes a Lead with a
              full analysis already completed.
            </div>

            {/* Pipeline Steps */}
            <div className="space-y-4">
              <h4 className="font-medium text-sm">Analysis Pipeline</h4>

              {/* Step 1 */}
              <div className="flex items-start gap-3 pl-2">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-500/10">
                  <Search className="h-4 w-4 text-blue-500" />
                </div>
                <div>
                  <p className="font-medium text-sm">1. Monitor Subreddit</p>
                  <p className="text-sm text-muted-foreground">
                    Every 5 minutes, Scout fetches new posts from configured subreddits.
                    Posts with empty bodies (hidden by users) are automatically skipped.
                  </p>
                </div>
              </div>

              {/* Step 2 */}
              <div className="flex items-start gap-3 pl-2">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-purple-500/10">
                  <FileText className="h-4 w-4 text-purple-500" />
                </div>
                <div>
                  <p className="font-medium text-sm">2. Generate User Summaries</p>
                  <p className="text-sm text-muted-foreground">
                    For each post author, Scout fetches their recent posts and comments, then generates
                    two AI summaries: <strong>Interests Summary</strong> (hobbies, lifestyle, values) and{' '}
                    <strong>Character Summary</strong> (personality, communication style). These are
                    cached for reuse in future analyses.
                  </p>
                </div>
              </div>

              {/* Step 3 */}
              <div className="flex items-start gap-3 pl-2">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-500/10">
                  <Brain className="h-4 w-4 text-amber-500" />
                </div>
                <div>
                  <p className="font-medium text-sm">3. Multi-Agent Analysis</p>
                  <p className="text-sm text-muted-foreground">
                    Six specialized AI agents analyze the post and user profile in parallel:
                  </p>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                    <div className="flex items-center gap-1.5">
                      <Users className="h-3 w-3 text-muted-foreground" />
                      <span>Demographics</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Sparkles className="h-3 w-3 text-muted-foreground" />
                      <span>Preferences</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Heart className="h-3 w-3 text-muted-foreground" />
                      <span>Relationship Goals</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <AlertTriangle className="h-3 w-3 text-muted-foreground" />
                      <span>Risk Flags</span>
                    </div>
                    <div className="flex items-center gap-1.5 col-span-2">
                      <span className="text-muted-foreground">+ Sexual Preferences</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Step 4 */}
              <div className="flex items-start gap-3 pl-2">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10">
                  <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                </div>
                <div>
                  <p className="font-medium text-sm">4. Meta-Analysis Decision</p>
                  <p className="text-sm text-muted-foreground">
                    A coordinator agent synthesizes all dimension results into a final recommendation:
                    <span className="text-emerald-600 dark:text-emerald-400 font-medium"> Suitable</span>,
                    <span className="text-amber-600 dark:text-amber-400 font-medium"> Needs Review</span>, or
                    <span className="text-red-600 dark:text-red-400 font-medium"> Not Recommended</span>.
                    Posts meeting your configured confidence threshold become Leads.
                  </p>
                </div>
              </div>

              {/* Step 5 */}
              <div className="flex items-start gap-3 pl-2">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-green-500/10">
                  <ArrowRight className="h-4 w-4 text-green-500" />
                </div>
                <div>
                  <p className="font-medium text-sm">5. Lead Creation</p>
                  <p className="text-sm text-muted-foreground">
                    Matching posts are saved as Leads with the full analysis already attached.
                    Visit the Leads page to review recommendations, read the reasoning, and
                    initiate contact when ready. You can also re-run analysis with updated prompts.
                  </p>
                </div>
              </div>
            </div>

            {/* Configuration Tips */}
            <div className="rounded-lg bg-muted/50 p-4 space-y-2">
              <h4 className="font-medium text-sm">Configuration Tips</h4>
              <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
                <li><strong>Search Query:</strong> Use Reddit search syntax (AND, OR, NOT) to filter posts</li>
                <li><strong>Min Confidence:</strong> Higher values (0.7+) = fewer but better-matched leads</li>
                <li><strong>Identity:</strong> Link to a persona for context-aware analysis</li>
                <li><strong>Auto-Analyze:</strong> Enable to process posts immediately as they&apos;re found</li>
              </ul>
            </div>
          </CardContent>
        )}
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
