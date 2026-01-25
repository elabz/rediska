'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft,
  CheckCircle,
  XCircle,
  AlertCircle,
  Loader2,
  ExternalLink,
  RefreshCw,
  UserPlus,
  ChevronDown,
  ChevronUp,
  User,
  Heart,
  Target,
  AlertTriangle,
  Flame,
} from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';

interface ScoutWatch {
  id: number;
  source_location: string;
  search_query: string | null;
  is_active: boolean;
}

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

interface AnalysisDimensions {
  demographics?: Record<string, unknown>;
  preferences?: Record<string, unknown>;
  relationship_goals?: Record<string, unknown>;
  risk_flags?: Record<string, unknown>;
  sexual_preferences?: Record<string, unknown>;
  meta_analysis?: Record<string, unknown>;
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
  analysis_dimensions: AnalysisDimensions | null;
  lead_id: number | null;
}

interface RunDetailResponse {
  run: ScoutWatchRun;
  posts: ScoutWatchPost[];
}

const LIMIT = 20;

const DIMENSION_CONFIG: Record<string, {
  title: string;
  icon: React.ReactNode;
  color: string;
}> = {
  demographics: {
    title: 'Demographics',
    icon: <User className="h-3 w-3" />,
    color: 'text-blue-500',
  },
  preferences: {
    title: 'Preferences',
    icon: <Heart className="h-3 w-3" />,
    color: 'text-pink-500',
  },
  relationship_goals: {
    title: 'Relationship Goals',
    icon: <Target className="h-3 w-3" />,
    color: 'text-purple-500',
  },
  risk_flags: {
    title: 'Risk Flags',
    icon: <AlertTriangle className="h-3 w-3" />,
    color: 'text-amber-500',
  },
  sexual_preferences: {
    title: 'Intimacy',
    icon: <Flame className="h-3 w-3" />,
    color: 'text-red-500',
  },
};

export default function ScoutWatchHistoryPage() {
  const params = useParams();
  const watchId = params.watchId as string;

  const [watch, setWatch] = useState<ScoutWatch | null>(null);
  const [runs, setRuns] = useState<ScoutWatchRun[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showOnlyWithNewPosts, setShowOnlyWithNewPosts] = useState(false);

  // Run detail state
  const [expandedRunId, setExpandedRunId] = useState<number | null>(null);
  const [runDetails, setRunDetails] = useState<Record<number, RunDetailResponse>>({});
  const [loadingRunId, setLoadingRunId] = useState<number | null>(null);

  // Post expansion state
  const [expandedPostId, setExpandedPostId] = useState<number | null>(null);

  // Action states
  const [reanalyzingPostId, setReanalyzingPostId] = useState<number | null>(null);
  const [addingToLeadsPostId, setAddingToLeadsPostId] = useState<number | null>(null);

  const fetchWatch = useCallback(async () => {
    try {
      const response = await fetch(`/api/core/scout-watches/${watchId}`, {
        credentials: 'include',
      });
      if (response.ok) {
        const data = await response.json();
        setWatch(data);
      }
    } catch (err) {
      console.error('Failed to fetch watch:', err);
    }
  }, [watchId]);

  const fetchRuns = useCallback(async (newOffset: number = 0, onlyWithNewPosts: boolean = showOnlyWithNewPosts) => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams({
        limit: LIMIT.toString(),
        offset: newOffset.toString(),
      });
      if (onlyWithNewPosts) {
        params.set('has_new_posts', 'true');
      }

      const response = await fetch(
        `/api/core/scout-watches/${watchId}/runs?${params}`,
        { credentials: 'include' }
      );

      if (!response.ok) {
        throw new Error('Failed to fetch run history');
      }

      const data = await response.json();
      setRuns(data.runs || []);
      setTotal(data.total || 0);
      setOffset(newOffset);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, [watchId, showOnlyWithNewPosts]);

  const fetchRunDetail = async (runId: number) => {
    if (runDetails[runId]) {
      setExpandedRunId(expandedRunId === runId ? null : runId);
      return;
    }

    setLoadingRunId(runId);
    try {
      const response = await fetch(
        `/api/core/scout-watches/${watchId}/runs/${runId}`,
        { credentials: 'include' }
      );

      if (!response.ok) {
        throw new Error('Failed to fetch run details');
      }

      const data = await response.json();
      setRunDetails(prev => ({ ...prev, [runId]: data }));
      setExpandedRunId(runId);
    } catch (err) {
      console.error('Failed to fetch run detail:', err);
    } finally {
      setLoadingRunId(null);
    }
  };

  const handleReanalyze = async (postId: number) => {
    setReanalyzingPostId(postId);
    try {
      const response = await fetch(
        `/api/core/scout-watches/${watchId}/posts/${postId}/reanalyze`,
        {
          method: 'POST',
          credentials: 'include',
        }
      );

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to trigger re-analysis');
      }

      // Refresh the run detail after a short delay
      setTimeout(() => {
        if (expandedRunId) {
          setRunDetails(prev => {
            const newDetails = { ...prev };
            delete newDetails[expandedRunId];
            return newDetails;
          });
          fetchRunDetail(expandedRunId);
        }
      }, 2000);
    } catch (err) {
      console.error('Reanalyze error:', err);
    } finally {
      setReanalyzingPostId(null);
    }
  };

  const handleAddToLeads = async (postId: number) => {
    setAddingToLeadsPostId(postId);
    try {
      const response = await fetch(
        `/api/core/scout-watches/${watchId}/posts/${postId}/add-to-leads`,
        {
          method: 'POST',
          credentials: 'include',
        }
      );

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to add to leads');
      }

      const data = await response.json();

      // Update the post in runDetails with new lead_id
      if (expandedRunId && runDetails[expandedRunId]) {
        setRunDetails(prev => ({
          ...prev,
          [expandedRunId]: {
            ...prev[expandedRunId],
            posts: prev[expandedRunId].posts.map(p =>
              p.id === postId ? { ...p, lead_id: data.lead_id } : p
            ),
          },
        }));
      }
    } catch (err) {
      console.error('Add to leads error:', err);
    } finally {
      setAddingToLeadsPostId(null);
    }
  };

  useEffect(() => {
    fetchWatch();
  }, [fetchWatch]);

  useEffect(() => {
    fetchRuns(0, showOnlyWithNewPosts);
  }, [showOnlyWithNewPosts]); // eslint-disable-line react-hooks/exhaustive-deps

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'Never';
    const utcDateStr = dateStr.endsWith('Z') ? dateStr : dateStr + 'Z';
    const date = new Date(utcDateStr);
    return date.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getRecommendationIcon = (recommendation: string | null) => {
    switch (recommendation) {
      case 'suitable':
        return <CheckCircle className="h-4 w-4 text-green-500" />;
      case 'not_recommended':
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
      case 'not_recommended':
      case 'not_suitable':
        return 'Not Suitable';
      case 'needs_review':
        return 'Needs Review';
      default:
        return 'Pending';
    }
  };

  const renderDimensionValue = (key: string, value: unknown): React.ReactNode => {
    if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>;
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    if (typeof value === 'number') return value.toString();
    if (Array.isArray(value)) {
      if (value.length === 0) return <span className="text-muted-foreground">None</span>;
      return value.join(', ');
    }
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  };

  const renderDimensionOutput = (dimension: string, output: Record<string, unknown> | undefined) => {
    if (!output) return null;

    // Filter out common fields we don't need to display
    const skipFields = ['evidence', 'model_config'];
    const entries = Object.entries(output).filter(([key]) => !skipFields.includes(key));

    return (
      <div className="space-y-1.5">
        {entries.map(([key, value]) => (
          <div key={key} className="flex items-start gap-2 text-xs">
            <span className="text-muted-foreground min-w-[120px] capitalize">
              {key.replace(/_/g, ' ')}:
            </span>
            <span className="flex-1">{renderDimensionValue(key, value)}</span>
          </div>
        ))}
      </div>
    );
  };

  if (loading && runs.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" asChild>
            <Link href="/settings/scout-watches">
              <ArrowLeft className="h-5 w-5" />
            </Link>
          </Button>
          <div>
            <h1 className="text-2xl font-bold">Run History</h1>
            {watch && (
              <p className="text-muted-foreground">
                {watch.source_location}
                {watch.search_query && ` • ${watch.search_query}`}
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Switch
            id="filter-new-posts"
            checked={showOnlyWithNewPosts}
            onCheckedChange={setShowOnlyWithNewPosts}
          />
          <Label htmlFor="filter-new-posts" className="text-sm">
            Only runs with new posts
          </Label>
        </div>
      </div>

      {error && (
        <div className="bg-destructive/10 text-destructive px-4 py-3 rounded-lg">
          {error}
        </div>
      )}

      {/* Runs List */}
      {runs.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <AlertCircle className="h-12 w-12 text-muted-foreground/50 mb-4" />
            <h3 className="text-lg font-medium mb-2">No Run History</h3>
            <p className="text-muted-foreground text-sm text-center max-w-md">
              This watch hasn&apos;t run yet. Go back and click &quot;Run Now&quot; to trigger a run.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {runs.map((run) => (
            <Card key={run.id} className={run.status === 'failed' ? 'border-destructive/50' : ''}>
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <Badge variant={
                        run.status === 'completed' ? 'default' :
                        run.status === 'failed' ? 'destructive' : 'secondary'
                      }>
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
                    onClick={() => fetchRunDetail(run.id)}
                    disabled={loadingRunId === run.id}
                  >
                    {loadingRunId === run.id ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : expandedRunId === run.id ? (
                      <>
                        <ChevronUp className="h-4 w-4 mr-1" />
                        Hide Posts
                      </>
                    ) : (
                      <>
                        <ChevronDown className="h-4 w-4 mr-1" />
                        View Posts
                      </>
                    )}
                  </Button>
                </div>

                {/* Expanded Posts */}
                {expandedRunId === run.id && runDetails[run.id] && (
                  <div className="mt-4 pt-4 border-t">
                    {runDetails[run.id].posts.length === 0 ? (
                      <p className="text-sm text-muted-foreground">No posts in this run.</p>
                    ) : (
                      <div className="space-y-3">
                        <h4 className="text-sm font-medium">
                          Posts ({runDetails[run.id].posts.length})
                        </h4>
                        {runDetails[run.id].posts.map((post) => (
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
                                    <div className="flex items-center flex-wrap gap-2 text-xs text-muted-foreground mt-1">
                                      {post.post_author && <span>u/{post.post_author}</span>}
                                      <span>{getRecommendationLabel(post.analysis_recommendation)}</span>
                                      {post.analysis_confidence !== null && (
                                        <span>({Math.round(post.analysis_confidence * 100)}%)</span>
                                      )}
                                      {post.lead_id && (
                                        <Link
                                          href={`/leads/${post.lead_id}`}
                                          className="text-blue-500 hover:underline"
                                          onClick={(e) => e.stopPropagation()}
                                        >
                                          Lead #{post.lead_id}
                                        </Link>
                                      )}
                                    </div>
                                  </div>
                                  <div className="flex items-center gap-1">
                                    {expandedPostId === post.id ? (
                                      <ChevronUp className="h-4 w-4 text-muted-foreground" />
                                    ) : (
                                      <ChevronDown className="h-4 w-4 text-muted-foreground" />
                                    )}
                                  </div>
                                </div>
                              </CollapsibleTrigger>

                              <CollapsibleContent>
                                <div className="mt-3 pt-3 border-t space-y-4">
                                  {/* Analysis Reasoning */}
                                  {(() => {
                                    // Get reasoning from analysis_reasoning or meta_analysis
                                    const reasoning = post.analysis_reasoning ||
                                      (post.analysis_dimensions?.meta_analysis as Record<string, unknown>)?.reasoning as string ||
                                      null;
                                    return reasoning ? (
                                      <div>
                                        <h5 className="text-xs font-medium text-muted-foreground mb-1">
                                          Reasoning:
                                        </h5>
                                        <p className="text-sm whitespace-pre-wrap bg-muted/50 p-2 rounded">
                                          {reasoning}
                                        </p>
                                      </div>
                                    ) : null;
                                  })()}

                                  {/* Analysis Dimensions */}
                                  {post.analysis_dimensions && (
                                    <div className="space-y-3">
                                      <h5 className="text-xs font-medium text-muted-foreground">
                                        Analysis Details:
                                      </h5>
                                      <div className="grid gap-3 md:grid-cols-2">
                                        {Object.entries(DIMENSION_CONFIG).map(([key, config]) => {
                                          const dimOutput = post.analysis_dimensions?.[key as keyof AnalysisDimensions];
                                          if (!dimOutput) return null;

                                          return (
                                            <div key={key} className="border rounded p-2">
                                              <div className={`flex items-center gap-1.5 mb-2 ${config.color}`}>
                                                {config.icon}
                                                <span className="text-xs font-medium">{config.title}</span>
                                              </div>
                                              {renderDimensionOutput(key, dimOutput as Record<string, unknown>)}
                                            </div>
                                          );
                                        })}
                                      </div>
                                    </div>
                                  )}

                                  {/* Action Buttons */}
                                  <div className="flex flex-wrap gap-2 pt-2">
                                    <a
                                      href={`https://reddit.com/comments/${post.external_post_id}`}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="text-xs text-blue-500 hover:underline flex items-center gap-1"
                                    >
                                      <ExternalLink className="h-3 w-3" />
                                      View on Reddit
                                    </a>

                                    <Button
                                      variant="outline"
                                      size="sm"
                                      className="h-7 text-xs"
                                      onClick={() => handleReanalyze(post.id)}
                                      disabled={reanalyzingPostId === post.id}
                                    >
                                      {reanalyzingPostId === post.id ? (
                                        <Loader2 className="h-3 w-3 animate-spin mr-1" />
                                      ) : (
                                        <RefreshCw className="h-3 w-3 mr-1" />
                                      )}
                                      Re-analyze
                                    </Button>

                                    {!post.lead_id && (
                                      <Button
                                        variant="outline"
                                        size="sm"
                                        className="h-7 text-xs"
                                        onClick={() => handleAddToLeads(post.id)}
                                        disabled={addingToLeadsPostId === post.id}
                                      >
                                        {addingToLeadsPostId === post.id ? (
                                          <Loader2 className="h-3 w-3 animate-spin mr-1" />
                                        ) : (
                                          <UserPlus className="h-3 w-3 mr-1" />
                                        )}
                                        Add to Leads
                                      </Button>
                                    )}
                                  </div>
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

      {/* Pagination */}
      {total > LIMIT && (
        <div className="flex items-center justify-center gap-4">
          <Button
            variant="outline"
            onClick={() => fetchRuns(Math.max(0, offset - LIMIT))}
            disabled={offset === 0 || loading}
          >
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">
            {offset + 1}-{Math.min(offset + LIMIT, total)} of {total}
          </span>
          <Button
            variant="outline"
            onClick={() => fetchRuns(offset + LIMIT)}
            disabled={offset + LIMIT >= total || loading}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
