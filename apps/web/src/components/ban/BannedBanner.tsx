'use client';

import { Ban, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { reasonLabel, type BanEntry } from '@/lib/banList';

export interface BannedBannerProps {
  entry: BanEntry;
  onLift?: () => void;
  lifting?: boolean;
  /** Extra line, e.g. why the compose box is disabled. */
  message?: string;
  className?: string;
}

/** Shown wherever a banned account is displayed; content itself is never hidden. */
export function BannedBanner({ entry, onLift, lifting, message, className }: BannedBannerProps) {
  return (
    <div
      role="status"
      className={cn(
        'flex items-start gap-3 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm',
        className,
      )}
    >
      <Ban className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-destructive">
          u/{entry.username} is banned — {reasonLabel(entry.reason)}
        </p>
        <p className="text-xs text-muted-foreground">
          Since {new Date(entry.created_at).toLocaleDateString()}
          {entry.notes ? ` · ${entry.notes.split('\n')[0]}` : ''}
        </p>
        {message && <p className="mt-1 text-xs text-muted-foreground">{message}</p>}
      </div>
      {onLift && (
        <Button variant="outline" size="sm" onClick={onLift} disabled={lifting}>
          {lifting && <Loader2 className="h-3 w-3 animate-spin" />}
          Lift ban
        </Button>
      )}
    </div>
  );
}
