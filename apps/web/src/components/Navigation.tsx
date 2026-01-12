'use client';

import { useState } from 'react';
import Link from 'next/link';

interface NavigationProps {
  currentPath?: string;
  onLogout?: () => void;
}

interface NavItem {
  label: string;
  href: string;
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Inbox', href: '/inbox' },
  { label: 'Leads', href: '/leads' },
  { label: 'Browse', href: '/browse' },
  { label: 'Directories', href: '/directories' },
  { label: 'Search', href: '/search' },
  { label: 'Ops', href: '/ops' },
  { label: 'Audit', href: '/audit' },
];

export function Navigation({ currentPath = '', onLogout }: NavigationProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  const handleLogout = () => {
    setMenuOpen(false);
    onLogout?.();
  };

  return (
    <nav
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0.75rem 1.5rem',
        borderBottom: '1px solid var(--border)',
        background: 'var(--background)',
      }}
    >
      {/* Logo/Brand */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '2rem' }}>
        <Link
          href="/"
          style={{
            fontSize: '1.25rem',
            fontWeight: 700,
            color: 'var(--primary)',
            textDecoration: 'none',
          }}
        >
          Rediska
        </Link>

        {/* Navigation Links */}
        <div style={{ display: 'flex', gap: '0.25rem' }}>
          {NAV_ITEMS.map((item) => {
            const isActive = currentPath === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                data-active={isActive ? 'true' : 'false'}
                style={{
                  padding: '0.5rem 0.75rem',
                  borderRadius: '6px',
                  fontSize: '0.875rem',
                  fontWeight: 500,
                  textDecoration: 'none',
                  color: isActive ? 'var(--primary)' : 'var(--foreground)',
                  background: isActive ? 'var(--primary-hover)' : 'transparent',
                }}
              >
                {item.label}
              </Link>
            );
          })}
        </div>
      </div>

      {/* User Menu */}
      <div style={{ position: 'relative' }}>
        <button
          aria-label="User menu"
          onClick={() => setMenuOpen(!menuOpen)}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '36px',
            height: '36px',
            borderRadius: '50%',
            border: '1px solid var(--border)',
            background: 'var(--background)',
            cursor: 'pointer',
            fontSize: '1rem',
          }}
        >
          U
        </button>

        {menuOpen && (
          <div
            style={{
              position: 'absolute',
              top: '100%',
              right: 0,
              marginTop: '0.5rem',
              minWidth: '150px',
              padding: '0.5rem',
              background: 'var(--background)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
              zIndex: 50,
            }}
          >
            <button
              onClick={handleLogout}
              style={{
                width: '100%',
                padding: '0.5rem 0.75rem',
                textAlign: 'left',
                background: 'transparent',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                fontSize: '0.875rem',
                color: 'var(--foreground)',
              }}
            >
              Logout
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}

export default Navigation;
