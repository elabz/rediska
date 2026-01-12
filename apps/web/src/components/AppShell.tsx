'use client';

import { useRouter } from 'next/navigation';
import { Sidebar } from './Sidebar';
import { cn } from '@/lib/utils';
import { SidebarProvider, useSidebar } from '@/contexts/SidebarContext';

interface AppShellProps {
  children: React.ReactNode;
}

function AppShellContent({ children }: AppShellProps) {
  const router = useRouter();
  const { isCollapsed } = useSidebar();

  const handleLogout = async () => {
    try {
      const response = await fetch('/api/core/auth/logout', {
        method: 'POST',
        credentials: 'include',
      });

      if (response.ok) {
        router.push('/login');
      }
    } catch {
      // Redirect anyway on error
      router.push('/login');
    }
  };

  // Sidebar width: 15rem (240px) expanded, 4rem (64px) collapsed
  const sidebarWidth = isCollapsed ? '4rem' : '15rem';

  return (
    <div className="min-h-screen bg-background">
      <Sidebar onLogout={handleLogout} />
      <main
        className="min-h-screen transition-all duration-300 pt-14 lg:pt-0"
        style={{
          paddingLeft: undefined, // Reset, will be set via CSS media query below
        }}
      >
        <style jsx>{`
          main {
            padding-left: 0;
          }
          @media (min-width: 1024px) {
            main {
              padding-left: ${sidebarWidth} !important;
            }
          }
        `}</style>
        {children}
      </main>
    </div>
  );
}

export function AppShell({ children }: AppShellProps) {
  return (
    <SidebarProvider>
      <AppShellContent>{children}</AppShellContent>
    </SidebarProvider>
  );
}

export default AppShell;
