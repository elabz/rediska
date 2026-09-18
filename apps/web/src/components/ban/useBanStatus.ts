'use client';

import { useCallback, useEffect, useState } from 'react';
import { fetchBanStatus, liftBan, type BanEntry } from '@/lib/banList';

export interface BanState {
  /** The active ban, or null when the account is contactable. */
  ban: BanEntry | null;
  loading: boolean;
  error: string | null;
  lifting: boolean;
  refresh: () => Promise<void>;
  lift: () => Promise<void>;
  /** Apply a ban created elsewhere (e.g. from BanDialog) without refetching. */
  setBan: (entry: BanEntry | null) => void;
}

/** Ban state of one username, with a lift action. */
export function useBanStatus(
  username: string | null | undefined,
  providerId = 'reddit',
  options: { skipFetch?: boolean } = {},
): BanState {
  const { skipFetch = false } = options;
  const [ban, setBan] = useState<BanEntry | null>(null);
  const [loading, setLoading] = useState(Boolean(username) && !skipFetch);
  const [error, setError] = useState<string | null>(null);
  const [lifting, setLifting] = useState(false);

  const refresh = useCallback(async () => {
    if (!username) {
      setBan(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const status = await fetchBanStatus(username, providerId);
      setBan(status.banned ? status.entry : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load ban status');
    } finally {
      setLoading(false);
    }
  }, [username, providerId]);

  useEffect(() => {
    if (!skipFetch) refresh();
  }, [refresh, skipFetch]);

  const lift = useCallback(async () => {
    if (!ban) return;
    setLifting(true);
    setError(null);
    try {
      await liftBan(ban.id);
      setBan(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to lift ban');
    } finally {
      setLifting(false);
    }
  }, [ban]);

  return { ban, loading, error, lifting, refresh, lift, setBan };
}
