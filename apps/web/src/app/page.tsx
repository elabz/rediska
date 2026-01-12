'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  Inbox,
  Users,
  Search,
  Globe,
  FolderOpen,
  Settings,
  ClipboardList,
  Link2,
  Sparkles,
  ArrowRight,
} from 'lucide-react';
import { BentoGrid } from '@/components/BentoGrid';
import { BentoCard, StatCard, ActionCard } from '@/components/BentoCard';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

interface User {
  id: number;
  username: string;
}

export default function Home() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    fetch('/api/core/auth/me', { credentials: 'include' })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        setUser(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const handleLogout = async () => {
    await fetch('/api/core/auth/logout', {
      method: 'POST',
      credentials: 'include',
    });
    setUser(null);
    router.push('/login');
  };

  // Loading state
  if (loading) {
    return (
      <main className="min-h-screen bg-background p-6 md:p-10">
        <div className="max-w-6xl mx-auto">
          <Skeleton className="h-12 w-48 mb-2" />
          <Skeleton className="h-5 w-96 mb-8" />
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {[...Array(6)].map((_, i) => (
              <Skeleton key={i} className="h-40 rounded-xl" />
            ))}
          </div>
        </div>
      </main>
    );
  }

  // Not logged in - show landing page
  if (!user) {
    return (
      <main className="min-h-screen bg-background flex items-center justify-center p-6">
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
              <Sparkles className="h-8 w-8" />
            </div>
            <CardTitle className="text-2xl">Welcome to Rediska</CardTitle>
            <CardDescription>
              Local-first conversation management and lead discovery system
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Button asChild className="w-full" size="lg">
              <Link href="/login">
                Login to Continue
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              Connect your accounts and start managing conversations
            </p>
          </CardContent>
        </Card>
      </main>
    );
  }

  // Logged in - show dashboard with Bento grid
  return (
    <main className="min-h-screen bg-background p-6 md:p-10">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight mb-1">
            Welcome back, {user.username}
          </h1>
          <p className="text-muted-foreground">
            Here&apos;s an overview of your workspace
          </p>
        </div>

        {/* Bento Grid Dashboard */}
        <BentoGrid>
          {/* Hero Card - Welcome */}
          <BentoCard
            variant="feature"
            size="wide"
            title="Get Started"
            description="Connect your Reddit account to begin receiving and managing conversations in Rediska."
            icon={<Sparkles className="h-5 w-5" />}
            action={
              <Button variant="secondary" size="sm" asChild>
                <Link href="/setup/identity">
                  <Link2 className="mr-2 h-4 w-4" />
                  Connect Reddit
                </Link>
              </Button>
            }
          />

          {/* Stats */}
          <StatCard
            title="Inbox"
            value="0"
            change="No new messages"
            icon={<Inbox className="h-5 w-5" />}
          />

          <StatCard
            title="Active Leads"
            value="0"
            change="Start discovering"
            icon={<Users className="h-5 w-5" />}
          />

          {/* Navigation Cards */}
          <ActionCard
            title="Inbox"
            description="View and respond to conversations"
            icon={<Inbox className="h-5 w-5" />}
            href="/inbox"
          />

          <ActionCard
            title="Leads"
            description="Discover and analyze potential contacts"
            icon={<Users className="h-5 w-5" />}
            href="/leads"
          />

          <ActionCard
            title="Search"
            description="Find content across all sources"
            icon={<Search className="h-5 w-5" />}
            href="/search"
          />

          <ActionCard
            title="Browse"
            description="Explore communities and sources"
            icon={<Globe className="h-5 w-5" />}
            href="/browse"
          />

          <ActionCard
            title="Directories"
            description="Organized contact directories"
            icon={<FolderOpen className="h-5 w-5" />}
            href="/directories"
          />

          <ActionCard
            title="Operations"
            description="System operations and monitoring"
            icon={<Settings className="h-5 w-5" />}
            href="/ops"
          />

          <ActionCard
            title="Audit Log"
            description="Track system activity and changes"
            icon={<ClipboardList className="h-5 w-5" />}
            href="/audit"
          />

          {/* Settings Card */}
          <BentoCard
            size="wide"
            variant="muted"
            title="Settings"
            description="Manage your Reddit connection and voice personas"
            icon={<Settings className="h-5 w-5" />}
            href="/settings/connection"
          >
            <div className="mt-4 flex items-center gap-2">
              <Button variant="outline" size="sm" asChild>
                <Link href="/settings/connection">
                  <Link2 className="mr-2 h-3 w-3" />
                  Connection
                </Link>
              </Button>
              <Button variant="outline" size="sm" asChild>
                <Link href="/settings/personas">
                  <Sparkles className="mr-2 h-3 w-3" />
                  Personas
                </Link>
              </Button>
              <Button variant="ghost" size="sm" onClick={handleLogout}>
                Logout
              </Button>
            </div>
          </BentoCard>
        </BentoGrid>
      </div>
    </main>
  );
}
