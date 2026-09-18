'use client';

import { useState } from 'react';
import { Ban, Loader2, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { BanDialog } from './BanDialog';
import { BannedBanner } from './BannedBanner';
import { useBanStatus, type BanState } from './useBanStatus';
import type { BanEntry } from '@/lib/banList';

export interface BanControlProps {
  username: string | null | undefined;
  providerId?: string;
  /** `button`: labelled button; `compact`: small ghost button for dense rows. */
  variant?: 'button' | 'compact';
  /** Render the banned banner (with Lift) instead of a Lift button when banned. */
  showBanner?: boolean;
  /** Use state owned by the parent (e.g. a page that also disables compose). */
  state?: BanState;
  /**
   * Skip the status lookup (list rows whose query already excludes banned
   * authors); shows Ban until the user bans. Banning is idempotent.
   */
  assumeNotBanned?: boolean;
  onChange?: (ban: BanEntry | null) => void;
}

/**
 * Ban / Lift for one account. Works for usernames with no stored account.
 * Mounted wherever an account is judged: conversation header, profile, lead
 * detail, scout history post, needs-review item.
 */
export function BanControl({
  username,
  providerId = 'reddit',
  variant = 'button',
  showBanner = false,
  state,
  assumeNotBanned = false,
  onChange,
}: BanControlProps) {
  const own = useBanStatus(state ? null : username, providerId, {
    skipFetch: assumeNotBanned,
  });
  const { ban, loading, lifting, lift, setBan, error } = state ?? own;
  const [open, setOpen] = useState(false);

  if (!username) return null;

  const handleLift = async () => {
    await lift();
    onChange?.(null);
  };

  if (ban) {
    if (showBanner) {
      return <BannedBanner entry={ban} onLift={handleLift} lifting={lifting} />;
    }
    return (
      <Button
        variant="outline"
        size="sm"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          handleLift();
        }}
        disabled={lifting}
        title={`Banned: ${ban.reason ?? ''}. Click to lift.`}
        className="text-destructive"
      >
        {lifting ? <Loader2 className="h-3 w-3 animate-spin" /> : <ShieldCheck className="h-3 w-3" />}
        Lift ban
      </Button>
    );
  }

  return (
    <>
      <Button
        variant={variant === 'compact' ? 'ghost' : 'outline'}
        size="sm"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen(true);
        }}
        disabled={loading}
        title={error ?? `Ban u/${username}`}
        className="text-muted-foreground hover:text-destructive"
      >
        <Ban className="h-3 w-3" />
        {variant === 'button' && 'Ban'}
      </Button>
      <BanDialog
        open={open}
        onOpenChange={setOpen}
        username={username}
        providerId={providerId}
        onBanned={(result) => {
          setBan(result.entry);
          onChange?.(result.entry);
        }}
      />
    </>
  );
}
