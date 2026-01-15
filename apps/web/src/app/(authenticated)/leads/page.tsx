'use client';

import { useState, useCallback, useEffect } from 'react';
import Link from 'next/link';
import {
  Loader2,
  RefreshCw,
  Filter,
  ExternalLink,
  ArrowUp,
  MessageSquare,
  Sparkles,
  CheckCircle,
  XCircle,
  Clock,
  AlertCircle,
  ChevronDown,
  MoreVertical,
  User,
  Calendar,
  Award,
  FileText,
  MessageCircle,
} from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { EmptyState } from '@/components';

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
}

interface LeadsResponse {
  leads: Lead[];
  total: number;
}

const STATUS_OPTIONS = [
  { value: 'all', label: 'All statuses' },
  { value: 'new', label: 'New' },
  { value: 'saved', label: 'Saved' },
  { value: 'ignored', label: 'Ignored' },
  { value: 'contact_queued', label: 'Contact Queued' },
  { value: 'contacted', label: 'Contacted' },
];

const STATUS_COLORS: Record<string, string> = {
  new: 'bg-blue-500/10 text-blue-600 border-blue-500/20',
  saved: 'bg-amber-500/10 text-amber-600 border-amber-500/20',
  ignored: 'bg-muted text-muted-foreground',
  contact_queued: 'bg-purple-500/10 text-purple-600 border-purple-500/20',
  contacted: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20',
};

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffHours < 1) return 'Just now';
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  // Include year if not current year
  const isCurrentYear = date.getFullYear() === now.getFullYear();
  if (isCurrentYear) {
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
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

function LeadCard({
  lead,
  onStatusChange,
  onAnalyze,
  onContact,
  isUpdating,
  isAnalyzing,
  isContacting,
}: {
  lead: Lead;
  onStatusChange: (status: string) => void;
  onAnalyze: () => void;
  onContact: () => void;
  isUpdating: boolean;
  isAnalyzing: boolean;
  isContacting: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const hasLongContent = lead.body_text && lead.body_text.length > 200;
  const displayText = isExpanded || !hasLongContent
    ? lead.body_text || ''
    : (lead.body_text || '').slice(0, 200) + '...';

  const authorInfo = lead.author_info;
  const hasAnalysis = authorInfo?.analysis_state === 'analyzed';

  return (
    <Card className="p-4">
      {/* Author Info Bar - Prominent at top */}
      {lead.author_username && (
        <div className="flex items-center gap-3 mb-3 pb-3 border-b border-border">
          <div className="flex items-center justify-center w-10 h-10 rounded-full bg-primary/10 text-primary shrink-0">
            <User className="h-5 w-5" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm">u/{lead.author_username}</span>
              {authorInfo?.is_verified && (
                <Badge variant="secondary" className="text-xs h-4 px-1">Verified</Badge>
              )}
              {authorInfo?.is_suspended && (
                <Badge variant="destructive" className="text-xs h-4 px-1">Suspended</Badge>
              )}
              {hasAnalysis && (
                <Badge variant="outline" className="text-xs h-4 px-1 text-emerald-600 border-emerald-500/30 bg-emerald-500/10">
                  Analyzed
                </Badge>
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
            {!authorInfo && !hasAnalysis && (
              <p className="text-xs text-muted-foreground mt-0.5">
                Click Analyze to fetch profile info
              </p>
            )}
          </div>
        </div>
      )}

      {/* Post Header */}
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex-1 min-w-0">
          <h3 className="font-medium text-sm leading-tight line-clamp-2">
            {lead.title || '(No title)'}
          </h3>
          <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground flex-wrap">
            <Badge variant="secondary" className="text-xs h-5 px-1.5">
              r/{lead.source_location}
            </Badge>
            {lead.post_created_at && (
              <>
                <span>•</span>
                <span>{formatDate(lead.post_created_at)}</span>
              </>
            )}
          </div>
        </div>

        {/* Status Badge */}
        <Badge
          variant="outline"
          className={`${STATUS_COLORS[lead.status] || ''} shrink-0`}
        >
          {lead.status.replace('_', ' ')}
        </Badge>
      </div>

      {/* Body */}
      {lead.body_text && (
        <div className="mb-3">
          <p className="text-sm text-muted-foreground whitespace-pre-wrap break-words">
            {displayText}
          </p>
          {hasLongContent && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsExpanded(!isExpanded)}
              className="mt-1 h-6 px-2 text-xs"
            >
              {isExpanded ? 'Show less' : 'Show more'}
              <ChevronDown className={`h-3 w-3 ml-1 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
            </Button>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between gap-2 pt-2 border-t border-border">
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {lead.score !== null && (
            <span className="flex items-center gap-1">
              <Sparkles className="h-3 w-3" />
              Score: {lead.score}
            </span>
          )}
          {lead.post_url && (
            <a
              href={lead.post_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-primary hover:underline"
            >
              <ExternalLink className="h-3 w-3" />
              View
            </a>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* Contact Button */}
          <Button
            variant="outline"
            size="sm"
            onClick={onContact}
            disabled={isContacting || !lead.author_username}
            title={!lead.author_username ? 'No author to contact' : 'Start a conversation with this user'}
          >
            {isContacting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <>
                <MessageSquare className="h-4 w-4 mr-1" />
                Contact
              </>
            )}
          </Button>

          {/* Analyze Button */}
          <Button
            variant="outline"
            size="sm"
            onClick={onAnalyze}
            disabled={isAnalyzing || !lead.author_account_id}
            title={!lead.author_account_id ? 'No author associated' : 'Analyze author profile'}
          >
            {isAnalyzing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <>
                <Sparkles className="h-4 w-4 mr-1" />
                Analyze
              </>
            )}
          </Button>

          {/* Status Dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" disabled={isUpdating}>
                {isUpdating ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <MoreVertical className="h-4 w-4" />
                )}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => onStatusChange('saved')}>
                <CheckCircle className="h-4 w-4 mr-2 text-amber-600" />
                Mark as Saved
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onStatusChange('contact_queued')}>
                <Clock className="h-4 w-4 mr-2 text-purple-600" />
                Queue for Contact
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onStatusChange('contacted')}>
                <MessageSquare className="h-4 w-4 mr-2 text-emerald-600" />
                Mark as Contacted
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onStatusChange('ignored')}>
                <XCircle className="h-4 w-4 mr-2 text-muted-foreground" />
                Ignore
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </Card>
  );
}

export default function LeadsPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState('all');
  const [updatingLeads, setUpdatingLeads] = useState<Set<number>>(new Set());
  const [analyzingLeads, setAnalyzingLeads] = useState<Set<number>>(new Set());
  const [contactingLeads, setContactingLeads] = useState<Set<number>>(new Set());
  const [contactError, setContactError] = useState<string | null>(null);

  const LIMIT = 20;

  const fetchLeads = useCallback(async (newOffset = 0) => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams({
        limit: String(LIMIT),
        offset: String(newOffset),
      });
      if (statusFilter && statusFilter !== 'all') params.set('status', statusFilter);

      const response = await fetch(`/api/core/leads?${params.toString()}`, {
        credentials: 'include',
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to fetch leads');
      }

      const data: LeadsResponse = await response.json();
      setLeads(data.leads);
      setTotal(data.total);
      setOffset(newOffset);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    fetchLeads();
  }, [fetchLeads]);

  const updateLeadStatus = useCallback(async (leadId: number, status: string) => {
    setUpdatingLeads(prev => {
      const next = new Set(prev);
      next.add(leadId);
      return next;
    });

    try {
      const response = await fetch(`/api/core/leads/${leadId}/status`, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to update status');
      }

      const updated = await response.json();
      setLeads(prev => prev.map(lead =>
        lead.id === leadId ? { ...lead, status: updated.status } : lead
      ));
    } catch (err) {
      console.error('Failed to update lead status:', err);
    } finally {
      setUpdatingLeads(prev => {
        const next = new Set(prev);
        next.delete(leadId);
        return next;
      });
    }
  }, []);

  const analyzeLead = useCallback(async (leadId: number) => {
    setAnalyzingLeads(prev => {
      const next = new Set(prev);
      next.add(leadId);
      return next;
    });

    try {
      const response = await fetch(`/api/core/leads/${leadId}/analyze`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to analyze lead');
      }

      // Refresh leads to get updated data
      fetchLeads(offset);
    } catch (err) {
      console.error('Failed to analyze lead:', err);
    } finally {
      setAnalyzingLeads(prev => {
        const next = new Set(prev);
        next.delete(leadId);
        return next;
      });
    }
  }, [fetchLeads, offset]);

  const contactLead = useCallback(async (leadId: number) => {
    setContactingLeads(prev => {
      const next = new Set(prev);
      next.add(leadId);
      return next;
    });

    setContactError(null);

    try {
      const response = await fetch(`/api/core/conversations/initiate/from-lead/${leadId}`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to initiate conversation');
      }

      const conversation = await response.json();
      window.location.href = `/inbox/${conversation.id}`;
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to start conversation';
      setContactError(errorMsg);
      console.error('Failed to contact lead:', err);
    } finally {
      setContactingLeads(prev => {
        const next = new Set(prev);
        next.delete(leadId);
        return next;
      });
    }
  }, []);

  const refresh = () => fetchLeads();

  if (loading && leads.length === 0) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  if (error && leads.length === 0) {
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
          <h1 className="text-2xl font-bold">Leads</h1>
          <p className="text-muted-foreground mt-1">
            {total} saved lead{total !== 1 ? 's' : ''}
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
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Status</label>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="h-9">
                <SelectValue placeholder="All statuses" />
              </SelectTrigger>
              <SelectContent>
                {STATUS_OPTIONS.map(opt => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </Card>

      {/* Error Alert */}
      {contactError && (
        <div className="rounded-lg border border-destructive bg-destructive/10 p-3">
          <div className="flex items-start gap-2">
            <AlertCircle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-sm font-medium text-destructive">
                Failed to start conversation
              </p>
              <p className="text-sm text-destructive/80 mt-1">
                {contactError}
              </p>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setContactError(null)}
              className="h-6 w-6 p-0"
            >
              <XCircle className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}

      {/* Leads List */}
      {leads.length === 0 ? (
        <EmptyState
          icon="🎯"
          title="No leads found"
          description={statusFilter && statusFilter !== 'all'
            ? `No leads with status "${statusFilter}". Try a different filter or browse for new leads.`
            : "You haven't saved any leads yet. Browse subreddits to find and save potential leads."
          }
        />
      ) : (
        <>
          <div className="space-y-3">
            {leads.map((lead) => (
              <LeadCard
                key={lead.id}
                lead={lead}
                onStatusChange={(status) => updateLeadStatus(lead.id, status)}
                onAnalyze={() => analyzeLead(lead.id)}
                onContact={() => contactLead(lead.id)}
                isUpdating={updatingLeads.has(lead.id)}
                isAnalyzing={analyzingLeads.has(lead.id)}
                isContacting={contactingLeads.has(lead.id)}
              />
            ))}
          </div>

          {/* Pagination */}
          {total > LIMIT && (
            <div className="flex items-center justify-center gap-4">
              <Button
                variant="outline"
                onClick={() => fetchLeads(Math.max(0, offset - LIMIT))}
                disabled={offset === 0 || loading}
              >
                Previous
              </Button>
              <span className="text-sm text-muted-foreground">
                {offset + 1}-{Math.min(offset + LIMIT, total)} of {total}
              </span>
              <Button
                variant="outline"
                onClick={() => fetchLeads(offset + LIMIT)}
                disabled={offset + LIMIT >= total || loading}
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
