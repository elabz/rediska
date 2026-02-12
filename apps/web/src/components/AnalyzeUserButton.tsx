'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';
import { Loader2, Sparkles, CheckCircle, Eye } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';

interface AnalyzeUserButtonProps {
  username: string;
  accountId?: number;
  variant?: 'button' | 'dropdown-item' | 'icon';
  size?: 'sm' | 'default' | 'lg' | 'icon';
  className?: string;
  onAnalysisQueued?: (taskId: string) => void;
  onError?: (error: string) => void;
}

export function AnalyzeUserButton({
  username,
  accountId,
  variant = 'button',
  size = 'sm',
  className,
  onAnalysisQueued,
  onError,
}: AnalyzeUserButtonProps) {
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isQueued, setIsQueued] = useState(false);

  // Profile link destination
  const profileLink = accountId ? `/profile/${accountId}` : '/directories';

  const handleAnalyze = useCallback(async (e?: React.MouseEvent) => {
    e?.stopPropagation();
    e?.preventDefault();

    if (isAnalyzing || isQueued || !username) return;

    setIsAnalyzing(true);

    try {
      const response = await fetch('/api/core/accounts/analyze-username', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.replace(/^u\//, '') }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to queue analysis');
      }

      const data = await response.json();
      setIsQueued(true);
      onAnalysisQueued?.(data.task_id);

      // Reset after a delay
      setTimeout(() => setIsQueued(false), 5000);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to analyze user';
      onError?.(errorMsg);
      console.error('Failed to analyze user:', err);
    } finally {
      setIsAnalyzing(false);
    }
  }, [username, isAnalyzing, isQueued, onAnalysisQueued, onError]);

  if (variant === 'dropdown-item') {
    return (
      <>
        <DropdownMenuItem
          onClick={handleAnalyze}
          disabled={isAnalyzing || isQueued}
          className={className}
        >
          {isAnalyzing ? (
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
          ) : isQueued ? (
            <CheckCircle className="h-4 w-4 mr-2 text-emerald-500" />
          ) : (
            <Sparkles className="h-4 w-4 mr-2" />
          )}
          {isQueued ? 'Analysis Queued' : 'Analyze User'}
        </DropdownMenuItem>
        <Link href={profileLink} onClick={(e) => e.stopPropagation()}>
          <DropdownMenuItem className={className}>
            <Eye className="h-4 w-4 mr-2" />
            {accountId ? 'View Profile' : 'View Analyzed'}
          </DropdownMenuItem>
        </Link>
      </>
    );
  }

  if (variant === 'icon') {
    return (
      <span className={cn('inline-flex items-center gap-0.5', className)}>
        <Button
          variant="ghost"
          size="icon"
          onClick={handleAnalyze}
          disabled={isAnalyzing || isQueued}
          className="h-6 w-6"
          title={isQueued ? 'Analysis queued' : `Analyze u/${username}`}
        >
          {isAnalyzing ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : isQueued ? (
            <CheckCircle className="h-3 w-3 text-emerald-500" />
          ) : (
            <Sparkles className="h-3 w-3" />
          )}
        </Button>
        <Link
          href={profileLink}
          onClick={(e) => e.stopPropagation()}
          title={accountId ? `View u/${username}'s profile` : 'View analyzed accounts'}
        >
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            asChild
          >
            <span>
              <Eye className="h-3 w-3" />
            </span>
          </Button>
        </Link>
      </span>
    );
  }

  // Default button variant
  return (
    <span className={cn('inline-flex items-center gap-1', className)}>
      <Button
        variant="outline"
        size={size}
        onClick={handleAnalyze}
        disabled={isAnalyzing || isQueued}
        title={`Analyze u/${username}'s profile, posts, and comments`}
      >
        {isAnalyzing ? (
          <Loader2 className="h-4 w-4 animate-spin mr-1" />
        ) : isQueued ? (
          <CheckCircle className="h-4 w-4 mr-1 text-emerald-500" />
        ) : (
          <Sparkles className="h-4 w-4 mr-1" />
        )}
        {isQueued ? 'Queued' : 'Analyze'}
      </Button>
      <Link
        href={profileLink}
        onClick={(e) => e.stopPropagation()}
        title={accountId ? `View u/${username}'s profile` : 'View analyzed accounts'}
      >
        <Button
          variant="ghost"
          size={size}
        >
          <Eye className="h-4 w-4 mr-1" />
          View
        </Button>
      </Link>
    </span>
  );
}
