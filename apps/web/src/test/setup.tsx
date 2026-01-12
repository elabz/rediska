import '@testing-library/jest-dom';
import React from 'react';
import { vi } from 'vitest';

// Mock next/navigation
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
  redirect: vi.fn(),
}));

// Mock next/link
vi.mock('next/link', () => ({
  default: function Link({ children, href, ...props }: { children: React.ReactNode; href: string }) {
    return React.createElement('a', { href, ...props }, children);
  },
}));

// Global fetch mock setup
global.fetch = vi.fn();

// Reset mocks between tests
beforeEach(() => {
  vi.clearAllMocks();
});
