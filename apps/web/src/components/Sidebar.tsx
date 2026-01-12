'use client';

import * as React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Inbox,
  Users,
  Search,
  Globe,
  FolderOpen,
  Settings,
  ClipboardList,
  LogOut,
  ChevronLeft,
  Menu,
  Link2,
  Sparkles,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import {
  Sheet,
  SheetContent,
  SheetTrigger,
} from '@/components/ui/sheet';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { useSidebar } from '@/contexts/SidebarContext';

interface NavItem {
  label: string;
  href: string;
  icon: React.ElementType;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

const NAV_SECTIONS: NavSection[] = [
  {
    title: 'Main',
    items: [
      { label: 'Inbox', href: '/inbox', icon: Inbox },
      { label: 'Leads', href: '/leads', icon: Users },
      { label: 'Search', href: '/search', icon: Search },
    ],
  },
  {
    title: 'Discovery',
    items: [
      { label: 'Browse', href: '/browse', icon: Globe },
      { label: 'Directories', href: '/directories', icon: FolderOpen },
    ],
  },
  {
    title: 'System',
    items: [
      { label: 'Ops', href: '/ops', icon: Settings },
      { label: 'Audit', href: '/audit', icon: ClipboardList },
    ],
  },
];

interface SidebarProps {
  onLogout?: () => void;
  username?: string;
}

function SidebarContent({ onLogout, username }: SidebarProps) {
  const pathname = usePathname();

  return (
    <div className="flex h-full flex-col">
      {/* Logo */}
      <div className="flex h-14 items-center border-b border-border px-4">
        <Link href="/" className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground font-bold">
            R
          </div>
          <span className="text-lg font-semibold">Rediska</span>
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-3 py-4">
        {NAV_SECTIONS.map((section, index) => (
          <div key={section.title} className={cn(index > 0 && 'mt-6')}>
            <h4 className="mb-2 px-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              {section.title}
            </h4>
            <div className="space-y-1">
              {section.items.map((item) => {
                const isActive = pathname === item.href;
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-200',
                      isActive
                        ? 'bg-primary text-primary-foreground shadow-sm'
                        : 'text-foreground hover:bg-accent hover:text-accent-foreground'
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    {item.label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Settings Links */}
      <div className="px-3 pb-2 space-y-1">
        <Link
          href="/settings/connection"
          className={cn(
            'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-200',
            pathname === '/settings/connection'
              ? 'bg-primary text-primary-foreground shadow-sm'
              : 'text-foreground hover:bg-accent hover:text-accent-foreground'
          )}
        >
          <Link2 className="h-4 w-4" />
          Connection
        </Link>
        <Link
          href="/settings/personas"
          className={cn(
            'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-200',
            pathname === '/settings/personas'
              ? 'bg-primary text-primary-foreground shadow-sm'
              : 'text-foreground hover:bg-accent hover:text-accent-foreground'
          )}
        >
          <Sparkles className="h-4 w-4" />
          Personas
        </Link>
      </div>

      <Separator />

      {/* User Menu */}
      <div className="p-3">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              className="w-full justify-start gap-3 px-3 py-2 h-auto"
            >
              <Avatar className="h-8 w-8">
                <AvatarFallback className="bg-secondary text-secondary-foreground">
                  {username?.charAt(0).toUpperCase() || 'U'}
                </AvatarFallback>
              </Avatar>
              <div className="flex flex-col items-start text-sm">
                <span className="font-medium">{username || 'User'}</span>
                <span className="text-xs text-muted-foreground">Account</span>
              </div>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56">
            <DropdownMenuLabel>My Account</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link href="/settings/connection" className="cursor-pointer">
                <Link2 className="mr-2 h-4 w-4" />
                Reddit Connection
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <Link href="/settings/personas" className="cursor-pointer">
                <Sparkles className="mr-2 h-4 w-4" />
                Voice Personas
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={onLogout}
              className="text-destructive focus:text-destructive cursor-pointer"
            >
              <LogOut className="mr-2 h-4 w-4" />
              Logout
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

export function Sidebar({ onLogout, username }: SidebarProps) {
  const { isCollapsed, toggleCollapsed } = useSidebar();

  return (
    <>
      {/* Desktop Sidebar */}
      <aside
        className={cn(
          'hidden lg:flex flex-col fixed left-0 top-0 z-40 h-screen border-r border-border bg-card transition-all duration-300',
          isCollapsed ? 'w-16' : 'w-60'
        )}
      >
        {!isCollapsed && <SidebarContent onLogout={onLogout} username={username} />}
        {isCollapsed && (
          <CollapsedSidebar onLogout={onLogout} />
        )}
        <Button
          variant="ghost"
          size="icon"
          className="absolute -right-3 top-6 h-6 w-6 rounded-full border border-border bg-background shadow-sm"
          onClick={toggleCollapsed}
        >
          <ChevronLeft
            className={cn(
              'h-3 w-3 transition-transform',
              isCollapsed && 'rotate-180'
            )}
          />
        </Button>
      </aside>

      {/* Mobile Sidebar */}
      <Sheet>
        <SheetTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="fixed left-4 top-4 z-50 lg:hidden"
          >
            <Menu className="h-5 w-5" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="w-60 p-0">
          <SidebarContent onLogout={onLogout} username={username} />
        </SheetContent>
      </Sheet>
    </>
  );
}

function CollapsedSidebar({ onLogout }: { onLogout?: () => void }) {
  const pathname = usePathname();

  const allItems = NAV_SECTIONS.flatMap((s) => s.items);

  return (
    <div className="flex h-full flex-col items-center py-4">
      {/* Logo */}
      <Link href="/" className="mb-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground font-bold">
          R
        </div>
      </Link>

      <Separator className="w-8 mb-4" />

      {/* Nav Icons */}
      <nav className="flex-1 flex flex-col items-center gap-2">
        {allItems.map((item) => {
          const isActive = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              title={item.label}
              className={cn(
                'flex h-9 w-9 items-center justify-center rounded-lg transition-all duration-200',
                isActive
                  ? 'bg-primary text-primary-foreground shadow-sm'
                  : 'text-foreground hover:bg-accent hover:text-accent-foreground'
              )}
            >
              <Icon className="h-4 w-4" />
            </Link>
          );
        })}
      </nav>

      <Separator className="w-8 mb-4" />

      {/* User */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" className="h-9 w-9">
            <Avatar className="h-7 w-7">
              <AvatarFallback className="bg-secondary text-secondary-foreground text-xs">
                U
              </AvatarFallback>
            </Avatar>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" side="right">
          <DropdownMenuItem asChild>
            <Link href="/settings/connection" className="cursor-pointer">
              <Link2 className="mr-2 h-4 w-4" />
              Connection
            </Link>
          </DropdownMenuItem>
          <DropdownMenuItem asChild>
            <Link href="/settings/personas" className="cursor-pointer">
              <Sparkles className="mr-2 h-4 w-4" />
              Personas
            </Link>
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onClick={onLogout}
            className="text-destructive focus:text-destructive cursor-pointer"
          >
            <LogOut className="mr-2 h-4 w-4" />
            Logout
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export default Sidebar;
