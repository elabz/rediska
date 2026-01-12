'use client';

import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Loader2, CheckCircle2, XCircle } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';

function CallbackHandler() {
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [message, setMessage] = useState('Completing Reddit authorization...');

  useEffect(() => {
    const code = searchParams.get('code');
    const state = searchParams.get('state');
    const error = searchParams.get('error');

    if (error) {
      setStatus('error');
      setMessage(`Reddit authorization failed: ${error}`);
      return;
    }

    if (!code || !state) {
      setStatus('error');
      setMessage('Missing authorization code or state');
      return;
    }

    // Call the backend callback endpoint
    fetch(`/api/core/providers/reddit/oauth/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`, {
      credentials: 'include',
    })
      .then(async (response) => {
        if (!response.ok) {
          const data = await response.json();
          throw new Error(data.detail || 'OAuth callback failed');
        }
        return response.json();
      })
      .then((data) => {
        setStatus('success');
        setMessage(`Connected as u/${data.identity.external_username}`);

        // Notify parent window and close
        if (window.opener) {
          window.opener.postMessage({ type: 'oauth_complete', identity: data.identity }, '*');
          setTimeout(() => window.close(), 1500);
        }
      })
      .catch((err) => {
        setStatus('error');
        setMessage(err.message || 'Failed to complete authorization');
      });
  }, [searchParams]);

  return (
    <>
      {status === 'loading' && (
        <>
          <Loader2 className="h-12 w-12 animate-spin text-primary mx-auto mb-4" />
          <p className="text-muted-foreground">{message}</p>
        </>
      )}

      {status === 'success' && (
        <>
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-emerald-500/10">
            <CheckCircle2 className="h-8 w-8 text-emerald-500" />
          </div>
          <h2 className="text-xl font-semibold mb-2">Connected!</h2>
          <p className="text-muted-foreground">{message}</p>
          <p className="text-xs text-muted-foreground mt-4">This window will close automatically...</p>
        </>
      )}

      {status === 'error' && (
        <>
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-destructive/10">
            <XCircle className="h-8 w-8 text-destructive" />
          </div>
          <h2 className="text-xl font-semibold mb-2">Connection Failed</h2>
          <p className="text-muted-foreground">{message}</p>
          <p className="text-xs text-muted-foreground mt-4">You can close this window and try again.</p>
        </>
      )}
    </>
  );
}

function LoadingFallback() {
  return (
    <>
      <Loader2 className="h-12 w-12 animate-spin text-primary mx-auto mb-4" />
      <p className="text-muted-foreground">Loading...</p>
    </>
  );
}

export default function RedditOAuthCallback() {
  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-background">
      <Card className="w-full max-w-sm text-center">
        <CardContent className="pt-8 pb-8">
          <Suspense fallback={<LoadingFallback />}>
            <CallbackHandler />
          </Suspense>
        </CardContent>
      </Card>
    </div>
  );
}
