import { useState, useEffect, useCallback } from 'react';

export interface Identity {
  id: number;
  provider_id: string;
  external_username: string;
  external_user_id: string | null;
  display_name: string;
  is_default: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface UseIdentitiesReturn {
  identities: Identity[];
  defaultIdentity: Identity | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useIdentities(): UseIdentitiesReturn {
  const [identities, setIdentities] = useState<Identity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchIdentities = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/core/identities', {
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error('Failed to fetch identities');
      }

      const data = await response.json();
      setIdentities(data.identities || data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchIdentities();
  }, [fetchIdentities]);

  const defaultIdentity = identities.find(i => i.is_default) || identities[0] || null;

  return {
    identities,
    defaultIdentity,
    loading,
    error,
    refresh: fetchIdentities,
  };
}

export default useIdentities;
