import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppShell } from './AppShell';

// Mock usePathname and useRouter
const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  usePathname: () => '/inbox',
  useRouter: () => ({
    push: mockPush,
    replace: vi.fn(),
    refresh: vi.fn(),
  }),
}));

describe('AppShell', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(global.fetch).mockClear();
  });

  describe('rendering', () => {
    it('renders navigation', () => {
      render(
        <AppShell>
          <div>Test content</div>
        </AppShell>
      );

      expect(screen.getByRole('navigation')).toBeInTheDocument();
    });

    it('renders children content', () => {
      render(
        <AppShell>
          <div>Test content</div>
        </AppShell>
      );

      expect(screen.getByText('Test content')).toBeInTheDocument();
    });

    it('renders main element for content', () => {
      render(
        <AppShell>
          <div>Test content</div>
        </AppShell>
      );

      expect(screen.getByRole('main')).toBeInTheDocument();
    });
  });

  describe('logout functionality', () => {
    it('calls logout API when logout is clicked', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
      } as Response);

      render(
        <AppShell>
          <div>Content</div>
        </AppShell>
      );

      const menuButton = screen.getByRole('button', { name: /user menu/i });
      await user.click(menuButton);

      const logoutButton = screen.getByRole('button', { name: /logout/i });
      await user.click(logoutButton);

      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith('/api/core/auth/logout', {
          method: 'POST',
          credentials: 'include',
        });
      });
    });

    it('redirects to login after successful logout', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
      } as Response);

      render(
        <AppShell>
          <div>Content</div>
        </AppShell>
      );

      const menuButton = screen.getByRole('button', { name: /user menu/i });
      await user.click(menuButton);

      const logoutButton = screen.getByRole('button', { name: /logout/i });
      await user.click(logoutButton);

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith('/login');
      });
    });

    it('redirects to login even on logout error', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch).mockRejectedValueOnce(new Error('Network error'));

      render(
        <AppShell>
          <div>Content</div>
        </AppShell>
      );

      const menuButton = screen.getByRole('button', { name: /user menu/i });
      await user.click(menuButton);

      const logoutButton = screen.getByRole('button', { name: /logout/i });
      await user.click(logoutButton);

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith('/login');
      });
    });
  });

  describe('navigation highlighting', () => {
    it('passes current path to Navigation', () => {
      render(
        <AppShell>
          <div>Content</div>
        </AppShell>
      );

      // The inbox link should be highlighted since usePathname returns '/inbox'
      const inboxLink = screen.getByRole('link', { name: /inbox/i });
      expect(inboxLink).toHaveAttribute('data-active', 'true');
    });
  });
});
