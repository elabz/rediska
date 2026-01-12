'use client';

import { useEffect, ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import { useSetupStatus } from '@/hooks/useSetupStatus';

interface OnboardingGateProps {
  children: ReactNode;
  loadingFallback?: ReactNode;
}

export function OnboardingGate({ children, loadingFallback }: OnboardingGateProps) {
  const router = useRouter();
  const { status, loading, error, refetch } = useSetupStatus();

  useEffect(() => {
    if (!loading && status && !status.onboarding_complete) {
      router.replace('/setup/identity');
    }
  }, [loading, status, router]);

  if (loading) {
    return (
      <div role="status" style={{ padding: '2rem', textAlign: 'center' }}>
        {loadingFallback || <p>Loading...</p>}
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: '2rem', textAlign: 'center' }}>
        <p style={{ color: '#dc2626', marginBottom: '1rem' }}>Error checking setup status</p>
        <button
          onClick={refetch}
          style={{
            padding: '0.5rem 1rem',
            background: 'var(--primary)',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  if (status && !status.onboarding_complete) {
    return (
      <div role="status" style={{ padding: '2rem', textAlign: 'center' }}>
        <p>Redirecting to setup...</p>
      </div>
    );
  }

  return <>{children}</>;
}
