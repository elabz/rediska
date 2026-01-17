'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft,
  Loader2,
  AlertCircle,
  ExternalLink,
  User,
  Calendar,
  Award,
  FileText,
  MessageCircle,
  MessageSquare,
  Sparkles,
  Brain,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

import { LeadAnalysisPanel } from './components/LeadAnalysisPanel';

// Types
interface AuthorInfo {
  username: string;
  account_created_at: string | null;
  karma: number | null;
  post_count: number | null;
  comment_count: number | null;
  analysis_state: string | null;
  bio: string | null;
  is_verified: boolean | null;
  is_suspended: boolean | null;
}

interface Lead {
  id: number;
  provider_id: string;
  source_location: string;
  external_post_id: string;
  post_url: string | null;
  title: string | null;
  body_text: string | null;
  author_username: string | null;
  author_account_id: number | null;
  author_info: AuthorInfo | null;
  post_created_at: string | null;
  status: string;
  score: number | null;
  created_at: string;
  latest_analysis_id: number | null;
  analysis_recommendation: string | null;
  analysis_confidence: number | null;
}

const STATUS_COLORS: Record<string, string> = {
  new: 'bg-blue-500/10 text-blue-600 border-blue-500/20',
  saved: 'bg-amber-500/10 text-amber-600 border-amber-500/20',
  ignored: 'bg-muted text-muted-foreground',
  contact_queued: 'bg-purple-500/10 text-purple-600 border-purple-500/20',
  contacted: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20',
};

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatAccountAge(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / 86400000);
  const diffMonths = Math.floor(diffDays / 30);
  const diffYears = Math.floor(diffDays / 365);

  if (diffYears >= 1) {
    return `${diffYears}y old`;
  }
  if (diffMonths >= 1) {
    return `${diffMonths}mo old`;
  }
  return `${diffDays}d old`;
}

function formatKarma(karma: number): string {
  if (karma >= 1000000) {
    return `${(karma / 1000000).toFixed(1)}M`;
  }
  if (karma >= 1000) {
    return `${(karma / 1000).toFixed(1)}K`;
  }
  return karma.toString();
}

export default function LeadDetailPage() {
  const params = useParams();
  const router = useRouter();
  const leadId = params.id as string;

  const [lead, setLead] = useState<Lead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isContacting, setIsContacting] = useState(false);

  const fetchLead = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`/api/core/leads/${leadId}`, {
        credentials: 'include',
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to fetch lead');
      }

      const data = await response.json();
      setLead(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, [leadId]);

  useEffect(() => {
    fetchLead();
  }, [fetchLead]);

  const handleContact = async () => {
    if (!lead) return;

    setIsContacting(true);
    try {
      const response = await fetch(`/api/core/conversations/initiate/from-lead/${lead.id}`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to initiate conversation');
      }

      const conversation = await response.json();
      router.push(`/inbox/${conversation.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start conversation');
    } finally {
      setIsContacting(false);
    }
  };

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  if (error || !lead) {
    return (
      <div className="max-w-4xl mx-auto">
        <Card className="p-8">
          <div className="text-center">
            <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
            <p className="text-destructive font-medium">{error || 'Lead not found'}</p>
            <Button variant="outline" onClick={() => router.push('/leads')} className="mt-4">
              Back to Leads
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  const authorInfo = lead.author_info;

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="sm" asChild>
          <Link href="/leads">
            <ArrowLeft className="h-4 w-4 mr-1" />
            Back to Leads
          </Link>
        </Button>
      </div>

      {/* Lead Info Card */}
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-2">
                <Badge variant="secondary" className="text-xs">
                  r/{lead.source_location}
                </Badge>
                <Badge
                  variant="outline"
                  className={STATUS_COLORS[lead.status] || ''}
                >
                  {lead.status.replace('_', ' ')}
                </Badge>
              </div>
              <CardTitle className="text-xl leading-tight">
                {lead.title || '(No title)'}
              </CardTitle>
              {lead.post_created_at && (
                <p className="text-sm text-muted-foreground mt-1">
                  Posted {formatDate(lead.post_created_at)}
                </p>
              )}
            </div>

            <div className="flex items-center gap-2 shrink-0">
              {lead.post_url && (
                <Button variant="outline" size="sm" asChild>
                  <a href={lead.post_url} target="_blank" rel="noopener noreferrer">
                    <ExternalLink className="h-4 w-4 mr-1" />
                    View Post
                  </a>
                </Button>
              )}
              <Button
                variant="default"
                size="sm"
                onClick={handleContact}
                disabled={isContacting || !lead.author_username}
              >
                {isContacting ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-1" />
                ) : (
                  <MessageSquare className="h-4 w-4 mr-1" />
                )}
                Contact
              </Button>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {/* Author Info */}
          {lead.author_username && (
            <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/50">
              <div className="flex items-center justify-center w-10 h-10 rounded-full bg-primary/10 text-primary shrink-0">
                <User className="h-5 w-5" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <Link
                    href={`/profile/${lead.author_account_id}`}
                    className="font-semibold text-sm hover:underline"
                  >
                    u/{lead.author_username}
                  </Link>
                  {authorInfo?.is_verified && (
                    <Badge variant="secondary" className="text-xs h-4 px-1">Verified</Badge>
                  )}
                  {authorInfo?.is_suspended && (
                    <Badge variant="destructive" className="text-xs h-4 px-1">Suspended</Badge>
                  )}
                </div>
                {authorInfo && (
                  <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground flex-wrap">
                    {authorInfo.account_created_at && (
                      <span className="flex items-center gap-1">
                        <Calendar className="h-3 w-3" />
                        {formatAccountAge(authorInfo.account_created_at)}
                      </span>
                    )}
                    {authorInfo.karma !== null && (
                      <span className="flex items-center gap-1">
                        <Award className="h-3 w-3" />
                        {formatKarma(authorInfo.karma)} karma
                      </span>
                    )}
                    {authorInfo.post_count !== null && authorInfo.post_count > 0 && (
                      <span className="flex items-center gap-1">
                        <FileText className="h-3 w-3" />
                        {authorInfo.post_count} posts
                      </span>
                    )}
                    {authorInfo.comment_count !== null && authorInfo.comment_count > 0 && (
                      <span className="flex items-center gap-1">
                        <MessageCircle className="h-3 w-3" />
                        {authorInfo.comment_count} comments
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Post Body */}
          {lead.body_text && (
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <p className="whitespace-pre-wrap break-words">{lead.body_text}</p>
            </div>
          )}

          {/* Score */}
          {lead.score !== null && (
            <div className="flex items-center gap-2 pt-2 border-t border-border">
              <Sparkles className="h-4 w-4 text-amber-500" />
              <span className="text-sm">
                Lead Score: <strong>{lead.score}</strong>
              </span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Multi-Agent Analysis Panel */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-500/10">
              <Brain className="h-5 w-5 text-purple-500" />
            </div>
            <div>
              <CardTitle className="text-lg">Multi-Agent Analysis</CardTitle>
              <p className="text-sm text-muted-foreground">
                AI-powered analysis across 6 dimensions
              </p>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <LeadAnalysisPanel
            leadId={lead.id}
            hasAnalysis={!!lead.latest_analysis_id}
            currentRecommendation={lead.analysis_recommendation}
            currentConfidence={lead.analysis_confidence}
            currentStatus={lead.status}
            onAnalysisComplete={fetchLead}
            onStatusChange={(newStatus) => {
              // Update local state immediately for responsive UI
              setLead(prev => prev ? { ...prev, status: newStatus } : null);
              // Optionally re-fetch to get full updated data
              fetchLead();
            }}
            onInitiateContact={handleContact}
          />
        </CardContent>
      </Card>
    </div>
  );
}
