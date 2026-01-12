import { useState, useEffect, useCallback } from 'react';

export interface SetupStatus {
  onboarding_complete: boolean;
  has_active_identity: boolean;
}

export interface UseSetupStatusReturn {
  status: SetupStatus | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useSetupStatus(): UseSetupStatusReturn {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/core/setup/status', {
        credentials: 'include',
      });

      if (response.ok) {
        const data = await response.json();
        setStatus(data);
      } else {
        setError('Failed to check setup status');
      }
    } catch {
      setError('Failed to check setup status');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  return {
    status,
    loading,
    error,
    refetch: fetchStatus,
  };
}
