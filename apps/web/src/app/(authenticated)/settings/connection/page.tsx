'use client';

import { useState, useEffect, useCallback } from 'react';
import { CheckCircle2, XCircle, RefreshCw, Loader2, ExternalLink, AlertTriangle, Copy, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Separator } from '@/components/ui/separator';

interface Connection {
  id: number;
  provider_id: string;
  external_username: string;
  is_active: boolean;
  created_at: string;
}

export default function ConnectionPage() {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [loading, setLoading] = useState(true);
  const [reconnecting, setReconnecting] = useState(false);

  const fetchConnection = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/core/identities', {
        credentials: 'include',
      });
      if (response.ok) {
        const data = await response.json();
        const identities = data.identities || [];
        // Get the active Reddit connection (or most recent if none active)
        const redditConnections = identities.filter(
          (i: Connection) => i.provider_id === 'reddit'
        );
        const activeConnection = redditConnections.find((i: Connection) => i.is_active);
        setConnection(activeConnection || redditConnections[redditConnections.length - 1] || null);
      }
    } catch {
      // Silent fail
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConnection();
  }, [fetchConnection]);

  // Listen for OAuth popup completion
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.data?.type === 'oauth_complete') {
        fetchConnection();
        setReconnecting(false);
      }
    };
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [fetchConnection]);

  const handleConnect = async () => {
    setReconnecting(true);
    try {
      // First, get the authorization URL from the API
      const response = await fetch('/api/core/providers/reddit/oauth/start', {
        credentials: 'include',
      });

      if (!response.ok) {
        const error = await response.json();
        alert(error.detail || 'Failed to start OAuth flow');
        setReconnecting(false);
        return;
      }

      const data = await response.json();

      // Open popup and redirect to Reddit's authorization page
      const width = 600;
      const height = 700;
      const left = window.screenX + (window.outerWidth - width) / 2;
      const top = window.screenY + (window.outerHeight - height) / 2;
      window.open(
        data.authorization_url,
        'oauth_popup',
        `width=${width},height=${height},left=${left},top=${top}`
      );
    } catch (error) {
      console.error('OAuth error:', error);
      alert('Failed to connect to Reddit. Please try again.');
      setReconnecting(false);
    }
  };

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto space-y-6">
        <div>
          <Skeleton className="h-8 w-48 mb-2" />
          <Skeleton className="h-4 w-64" />
        </div>
        <Skeleton className="h-48 rounded-xl" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Reddit Connection</h1>
        <p className="text-muted-foreground text-sm">
          Manage your Reddit account connection
        </p>
      </div>

      {/* Connection Status Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-[#FF4500]/10">
                <svg className="h-6 w-6 text-[#FF4500]" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0zm5.01 4.744c.688 0 1.25.561 1.25 1.249a1.25 1.25 0 0 1-2.498.056l-2.597-.547-.8 3.747c1.824.07 3.48.632 4.674 1.488.308-.309.73-.491 1.207-.491.968 0 1.754.786 1.754 1.754 0 .716-.435 1.333-1.01 1.614a3.111 3.111 0 0 1 .042.52c0 2.694-3.13 4.87-7.004 4.87-3.874 0-7.004-2.176-7.004-4.87 0-.183.015-.366.043-.534A1.748 1.748 0 0 1 4.028 12c0-.968.786-1.754 1.754-1.754.463 0 .898.196 1.207.49 1.207-.883 2.878-1.43 4.744-1.487l.885-4.182a.342.342 0 0 1 .14-.197.35.35 0 0 1 .238-.042l2.906.617a1.214 1.214 0 0 1 1.108-.701zM9.25 12C8.561 12 8 12.562 8 13.25c0 .687.561 1.248 1.25 1.248.687 0 1.248-.561 1.248-1.249 0-.688-.561-1.249-1.249-1.249zm5.5 0c-.687 0-1.248.561-1.248 1.25 0 .687.561 1.248 1.249 1.248.688 0 1.249-.561 1.249-1.249 0-.687-.562-1.249-1.25-1.249zm-5.466 3.99a.327.327 0 0 0-.231.094.33.33 0 0 0 0 .463c.842.842 2.484.913 2.961.913.477 0 2.105-.056 2.961-.913a.361.361 0 0 0 .029-.463.33.33 0 0 0-.464 0c-.547.533-1.684.73-2.512.73-.828 0-1.979-.196-2.512-.73a.326.326 0 0 0-.232-.095z"/>
                </svg>
              </div>
              <div>
                <CardTitle className="text-lg">Reddit</CardTitle>
                <CardDescription>
                  {connection
                    ? `Connected as u/${connection.external_username}`
                    : 'Not connected'}
                </CardDescription>
              </div>
            </div>
            {connection && (
              <Badge variant={connection.is_active ? 'success' : 'secondary'}>
                {connection.is_active ? (
                  <>
                    <CheckCircle2 className="mr-1 h-3 w-3" />
                    Active
                  </>
                ) : (
                  <>
                    <XCircle className="mr-1 h-3 w-3" />
                    Inactive
                  </>
                )}
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {connection ? (
            <>
              <div className="rounded-lg bg-muted/50 p-4 space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Username</span>
                  <span className="font-medium">u/{connection.external_username}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Connected since</span>
                  <span className="font-medium">
                    {new Date(connection.created_at).toLocaleDateString()}
                  </span>
                </div>
              </div>

              <div className="flex gap-3">
                <Button
                  variant="outline"
                  onClick={handleConnect}
                  disabled={reconnecting}
                >
                  {reconnecting ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Reconnecting...
                    </>
                  ) : (
                    <>
                      <RefreshCw className="mr-2 h-4 w-4" />
                      Reconnect
                    </>
                  )}
                </Button>
                <Button variant="ghost" asChild>
                  <a
                    href={`https://reddit.com/user/${connection.external_username}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <ExternalLink className="mr-2 h-4 w-4" />
                    View Profile
                  </a>
                </Button>
              </div>
            </>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">
                Connect your Reddit account to start managing conversations and discovering leads.
              </p>
              <Button onClick={handleConnect} disabled={reconnecting}>
                {reconnecting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Connecting...
                  </>
                ) : (
                  <>
                    <svg className="mr-2 h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M12 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0zm5.01 4.744c.688 0 1.25.561 1.25 1.249a1.25 1.25 0 0 1-2.498.056l-2.597-.547-.8 3.747c1.824.07 3.48.632 4.674 1.488.308-.309.73-.491 1.207-.491.968 0 1.754.786 1.754 1.754 0 .716-.435 1.333-1.01 1.614a3.111 3.111 0 0 1 .042.52c0 2.694-3.13 4.87-7.004 4.87-3.874 0-7.004-2.176-7.004-4.87 0-.183.015-.366.043-.534A1.748 1.748 0 0 1 4.028 12c0-.968.786-1.754 1.754-1.754.463 0 .898.196 1.207.49 1.207-.883 2.878-1.43 4.744-1.487l.885-4.182a.342.342 0 0 1 .14-.197.35.35 0 0 1 .238-.042l2.906.617a1.214 1.214 0 0 1 1.108-.701zM9.25 12C8.561 12 8 12.562 8 13.25c0 .687.561 1.248 1.25 1.248.687 0 1.248-.561 1.248-1.249 0-.688-.561-1.249-1.249-1.249zm5.5 0c-.687 0-1.248.561-1.248 1.25 0 .687.561 1.248 1.249 1.248.688 0 1.249-.561 1.249-1.249 0-.687-.562-1.249-1.25-1.249zm-5.466 3.99a.327.327 0 0 0-.231.094.33.33 0 0 0 0 .463c.842.842 2.484.913 2.961.913.477 0 2.105-.056 2.961-.913a.361.361 0 0 0 .029-.463.33.33 0 0 0-.464 0c-.547.533-1.684.73-2.512.73-.828 0-1.979-.196-2.512-.73a.326.326 0 0 0-.232-.095z"/>
                    </svg>
                    Connect Reddit Account
                  </>
                )}
              </Button>
            </>
          )}
        </CardContent>
      </Card>

      {/* How it works Card */}
      <Card className="bg-muted/30">
        <CardContent className="pt-6">
          <h3 className="font-medium mb-3">How it works</h3>
          <ul className="text-sm text-muted-foreground space-y-2">
            <li className="flex gap-2">
              <span className="text-primary">•</span>
              <span>Messages you send through Rediska appear as from <strong className="text-foreground">u/{connection?.external_username || 'your-username'}</strong></span>
            </li>
            <li className="flex gap-2">
              <span className="text-primary">•</span>
              <span>Your OAuth tokens are stored securely and used to access the Reddit API</span>
            </li>
            <li className="flex gap-2">
              <span className="text-primary">•</span>
              <span>Reconnect if you experience authentication issues</span>
            </li>
          </ul>
        </CardContent>
      </Card>

      {/* Reddit API Setup Guide */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-amber-500" />
            <CardTitle className="text-lg">Reddit API Setup Required</CardTitle>
          </div>
          <CardDescription>
            Before connecting, you need to create a Reddit API application.
            Use a <strong>script</strong> type app for personal use (no approval needed).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Step 1 */}
          <div className="space-y-2">
            <h4 className="font-medium flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold">1</span>
              Create a Reddit Application
            </h4>
            <p className="text-sm text-muted-foreground ml-8">
              Go to{' '}
              <a
                href="https://www.reddit.com/prefs/apps"
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary hover:underline inline-flex items-center gap-1"
              >
                reddit.com/prefs/apps
                <ExternalLink className="h-3 w-3" />
              </a>
              {' '}and click <strong>&quot;create another app...&quot;</strong> at the bottom of the page.
            </p>
          </div>

          {/* Step 2 */}
          <div className="space-y-3">
            <h4 className="font-medium flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold">2</span>
              Fill in the Application Details
            </h4>
            <div className="ml-8 space-y-3">
              <div className="rounded-lg border bg-card p-4 space-y-3">
                <div className="grid gap-2">
                  <div className="flex justify-between items-center text-sm">
                    <span className="text-muted-foreground">Name</span>
                    <code className="bg-muted px-2 py-0.5 rounded text-xs">Rediska</code>
                  </div>
                  <Separator />
                  <div className="flex justify-between items-center text-sm">
                    <span className="text-muted-foreground">App type</span>
                    <Badge variant="secondary">script</Badge>
                    <span className="text-xs text-muted-foreground">(personal use)</span>
                  </div>
                  <Separator />
                  <div className="flex justify-between items-center text-sm">
                    <span className="text-muted-foreground">Description</span>
                    <code className="bg-muted px-2 py-0.5 rounded text-xs">Optional</code>
                  </div>
                  <Separator />
                  <div className="flex justify-between items-center text-sm">
                    <span className="text-muted-foreground">About URL</span>
                    <code className="bg-muted px-2 py-0.5 rounded text-xs">Optional</code>
                  </div>
                  <Separator />
                  <div className="text-sm space-y-1">
                    <div className="flex justify-between items-center">
                      <span className="text-muted-foreground">Redirect URI</span>
                      <CopyableCode text="https://rediska.local/oauth/reddit/callback" />
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Use your actual domain in production instead of localhost
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Step 3 */}
          <div className="space-y-3">
            <h4 className="font-medium flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold">3</span>
              Get Your Credentials
            </h4>
            <div className="ml-8 space-y-2">
              <p className="text-sm text-muted-foreground">
                After creating the app, you&apos;ll see your credentials:
              </p>
              <div className="rounded-lg border bg-card p-4 space-y-3">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-xs">Client ID</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Located directly under your app name (looks like: <code className="bg-muted px-1 rounded">abcDEF123XYZ78</code>)
                  </p>
                </div>
                <Separator />
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-xs">Client Secret</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Labeled as &quot;secret&quot; below the Client ID. Keep this private!
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Step 4 */}
          <div className="space-y-3">
            <h4 className="font-medium flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold">4</span>
              Configure Rediska Backend
            </h4>
            <div className="ml-8 space-y-2">
              <p className="text-sm text-muted-foreground">
                Add these environment variables to your backend configuration:
              </p>
              <div className="rounded-lg border bg-zinc-950 p-4 font-mono text-sm text-zinc-100 space-y-1 overflow-x-auto">
                <div className="text-zinc-500"># Reddit OAuth</div>
                <div>PROVIDER_REDDIT_ENABLED=<span className="text-emerald-400">true</span></div>
                <div>PROVIDER_REDDIT_CLIENT_ID=<span className="text-amber-400">your_client_id</span></div>
                <div>PROVIDER_REDDIT_CLIENT_SECRET=<span className="text-amber-400">your_client_secret</span></div>
                <div>PROVIDER_REDDIT_REDIRECT_URI=<span className="text-emerald-400">https://rediska.local/oauth/reddit/callback</span></div>
                <div>PROVIDER_REDDIT_USER_AGENT=<span className="text-emerald-400">Rediska/1.0 by /u/</span><span className="text-amber-400">your_username</span></div>
                <div className="text-zinc-500 mt-2"># Encryption key for token storage (generate with: python -c &quot;from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())&quot;)</div>
                <div>ENCRYPTION_KEY=<span className="text-amber-400">your_fernet_key</span></div>
              </div>
              <p className="text-xs text-muted-foreground">
                Then restart your backend service for changes to take effect.
              </p>
            </div>
          </div>

          <Separator />

          {/* Resources */}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" asChild>
              <a
                href="https://www.reddit.com/prefs/apps"
                target="_blank"
                rel="noopener noreferrer"
              >
                <ExternalLink className="mr-2 h-3 w-3" />
                Reddit Apps Page
              </a>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <a
                href="https://github.com/reddit-archive/reddit/wiki/oauth2"
                target="_blank"
                rel="noopener noreferrer"
              >
                <ExternalLink className="mr-2 h-3 w-3" />
                Reddit OAuth2 Docs
              </a>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function CopyableCode({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="inline-flex items-center gap-1 bg-muted hover:bg-muted/80 px-2 py-0.5 rounded text-xs font-mono transition-colors"
      title="Click to copy"
    >
      <span className="max-w-[200px] truncate">{text}</span>
      {copied ? (
        <Check className="h-3 w-3 text-emerald-500" />
      ) : (
        <Copy className="h-3 w-3 text-muted-foreground" />
      )}
    </button>
  );
}
