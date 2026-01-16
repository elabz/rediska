'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Loader2,
  AlertCircle,
  RotateCcw,
  Clock,
  FileText,
  ChevronDown,
  ChevronUp,
  Check,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
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
import { cn } from '@/lib/utils';

interface PromptVersion {
  id: number;
  version: number;
  system_prompt: string;
  temperature: number;
  max_tokens: number;
  is_active: boolean;
  created_at: string;
  created_by: string;
  notes: string | null;
}

interface VersionHistoryProps {
  dimension: string;
  currentVersion: number;
  onRollback: () => void;
}

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

function formatPromptPreview(prompt: string, maxLength: number = 200): string {
  if (prompt.length <= maxLength) return prompt;
  return prompt.substring(0, maxLength) + '...';
}

export function VersionHistory({ dimension, currentVersion, onRollback }: VersionHistoryProps) {
  const [versions, setVersions] = useState<PromptVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedVersion, setExpandedVersion] = useState<number | null>(null);
  const [rollbackTarget, setRollbackTarget] = useState<PromptVersion | null>(null);
  const [rollingBack, setRollingBack] = useState(false);

  const fetchVersions = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`/api/core/agent-prompts/${dimension}/versions`, {
        credentials: 'include',
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to fetch versions');
      }

      const data = await response.json();
      setVersions(data.versions || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, [dimension]);

  useEffect(() => {
    fetchVersions();
  }, [fetchVersions]);

  const handleRollback = async () => {
    if (!rollbackTarget) return;

    setRollingBack(true);

    try {
      const response = await fetch(`/api/core/agent-prompts/${dimension}/rollback`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          target_version: rollbackTarget.version,
        }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to rollback');
      }

      setRollbackTarget(null);
      onRollback();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to rollback');
    } finally {
      setRollingBack(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive bg-destructive/10 p-4">
        <div className="flex items-center gap-2">
          <AlertCircle className="h-5 w-5 text-destructive" />
          <p className="text-sm text-destructive">{error}</p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchVersions} className="mt-3">
          Try Again
        </Button>
      </div>
    );
  }

  if (versions.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <FileText className="h-12 w-12 mx-auto mb-4 opacity-50" />
        <p>No version history available</p>
      </div>
    );
  }

  return (
    <>
      <div className="space-y-3">
        {versions.map((version) => {
          const isExpanded = expandedVersion === version.version;
          const isCurrent = version.version === currentVersion;

          return (
            <Collapsible
              key={version.id}
              open={isExpanded}
              onOpenChange={(open) => setExpandedVersion(open ? version.version : null)}
            >
              <div
                className={cn(
                  'rounded-lg border transition-colors',
                  isCurrent ? 'border-primary/50 bg-primary/5' : 'hover:border-muted-foreground/30'
                )}
              >
                <CollapsibleTrigger asChild>
                  <button className="w-full p-4 text-left">
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-3">
                        <div className="flex flex-col items-center">
                          <Badge
                            variant={isCurrent ? 'default' : 'secondary'}
                            className="text-xs"
                          >
                            v{version.version}
                          </Badge>
                          {isCurrent && (
                            <span className="text-[10px] text-primary mt-1 font-medium">
                              Current
                            </span>
                          )}
                        </div>
                        <div>
                          <div className="flex items-center gap-2 text-sm">
                            <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                            <span>{formatDate(version.created_at)}</span>
                          </div>
                          {version.notes && (
                            <p className="text-sm text-muted-foreground mt-1">
                              {version.notes}
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {!isCurrent && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              setRollbackTarget(version);
                            }}
                            className="h-8"
                          >
                            <RotateCcw className="h-3.5 w-3.5 mr-1" />
                            Rollback
                          </Button>
                        )}
                        {isExpanded ? (
                          <ChevronUp className="h-4 w-4 text-muted-foreground" />
                        ) : (
                          <ChevronDown className="h-4 w-4 text-muted-foreground" />
                        )}
                      </div>
                    </div>
                  </button>
                </CollapsibleTrigger>

                <CollapsibleContent>
                  <div className="px-4 pb-4 pt-0 border-t">
                    <div className="mt-4 space-y-3">
                      {/* Parameters */}
                      <div className="flex gap-4 text-sm">
                        <div>
                          <span className="text-muted-foreground">Temperature:</span>{' '}
                          <span className="font-medium">{version.temperature}</span>
                        </div>
                        <div>
                          <span className="text-muted-foreground">Max Tokens:</span>{' '}
                          <span className="font-medium">{version.max_tokens.toLocaleString()}</span>
                        </div>
                        <div>
                          <span className="text-muted-foreground">Length:</span>{' '}
                          <span className="font-medium">
                            {version.system_prompt.length.toLocaleString()} chars
                          </span>
                        </div>
                      </div>

                      {/* Prompt Preview */}
                      <div className="rounded-md bg-muted/50 p-3">
                        <p className="text-xs text-muted-foreground mb-1">System Prompt Preview:</p>
                        <pre className="text-sm font-mono whitespace-pre-wrap break-words">
                          {formatPromptPreview(version.system_prompt, 500)}
                        </pre>
                      </div>
                    </div>
                  </div>
                </CollapsibleContent>
              </div>
            </Collapsible>
          );
        })}
      </div>

      {/* Rollback Confirmation Dialog */}
      <AlertDialog open={!!rollbackTarget} onOpenChange={() => setRollbackTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Rollback to Version {rollbackTarget?.version}?</AlertDialogTitle>
            <AlertDialogDescription>
              This will create a new version with the content from version {rollbackTarget?.version}.
              The current version will be preserved in the history.
              {rollbackTarget?.notes && (
                <span className="block mt-2 text-foreground">
                  Notes: &ldquo;{rollbackTarget.notes}&rdquo;
                </span>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={rollingBack}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleRollback} disabled={rollingBack}>
              {rollingBack ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Rolling back...
                </>
              ) : (
                <>
                  <Check className="h-4 w-4 mr-2" />
                  Confirm Rollback
                </>
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
