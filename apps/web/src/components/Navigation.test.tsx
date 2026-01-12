import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Navigation } from './Navigation';

describe('Navigation', () => {
  describe('rendering', () => {
    it('renders the app name/logo', () => {
      render(<Navigation />);

      expect(screen.getByText(/rediska/i)).toBeInTheDocument();
    });

    it('renders all navigation links', () => {
      render(<Navigation />);

      expect(screen.getByRole('link', { name: /inbox/i })).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /leads/i })).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /browse/i })).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /directories/i })).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /search/i })).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /ops/i })).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /audit/i })).toBeInTheDocument();
    });

    it('renders navigation as nav element for accessibility', () => {
      render(<Navigation />);

      expect(screen.getByRole('navigation')).toBeInTheDocument();
    });
  });

  describe('link destinations', () => {
    it('inbox link points to /inbox', () => {
      render(<Navigation />);

      const link = screen.getByRole('link', { name: /inbox/i });
      expect(link).toHaveAttribute('href', '/inbox');
    });

    it('leads link points to /leads', () => {
      render(<Navigation />);

      const link = screen.getByRole('link', { name: /leads/i });
      expect(link).toHaveAttribute('href', '/leads');
    });

    it('browse link points to /browse', () => {
      render(<Navigation />);

      const link = screen.getByRole('link', { name: /browse/i });
      expect(link).toHaveAttribute('href', '/browse');
    });

    it('directories link points to /directories', () => {
      render(<Navigation />);

      const link = screen.getByRole('link', { name: /directories/i });
      expect(link).toHaveAttribute('href', '/directories');
    });

    it('search link points to /search', () => {
      render(<Navigation />);

      const link = screen.getByRole('link', { name: /search/i });
      expect(link).toHaveAttribute('href', '/search');
    });

    it('ops link points to /ops', () => {
      render(<Navigation />);

      const link = screen.getByRole('link', { name: /ops/i });
      expect(link).toHaveAttribute('href', '/ops');
    });

    it('audit link points to /audit', () => {
      render(<Navigation />);

      const link = screen.getByRole('link', { name: /audit/i });
      expect(link).toHaveAttribute('href', '/audit');
    });
  });

  describe('active state', () => {
    it('highlights active route when currentPath is provided', () => {
      render(<Navigation currentPath="/inbox" />);

      const inboxLink = screen.getByRole('link', { name: /inbox/i });
      expect(inboxLink).toHaveAttribute('data-active', 'true');
    });

    it('does not highlight inactive routes', () => {
      render(<Navigation currentPath="/inbox" />);

      const leadsLink = screen.getByRole('link', { name: /leads/i });
      expect(leadsLink).toHaveAttribute('data-active', 'false');
    });
  });

  describe('user menu', () => {
    it('renders user menu button', () => {
      render(<Navigation />);

      expect(screen.getByRole('button', { name: /user menu/i })).toBeInTheDocument();
    });

    it('shows logout option in user menu', async () => {
      const user = userEvent.setup();
      render(<Navigation />);

      const menuButton = screen.getByRole('button', { name: /user menu/i });
      await user.click(menuButton);

      expect(screen.getByRole('button', { name: /logout/i })).toBeInTheDocument();
    });

    it('calls onLogout when logout is clicked', async () => {
      const onLogout = vi.fn();
      const user = userEvent.setup();
      render(<Navigation onLogout={onLogout} />);

      const menuButton = screen.getByRole('button', { name: /user menu/i });
      await user.click(menuButton);

      const logoutButton = screen.getByRole('button', { name: /logout/i });
      await user.click(logoutButton);

      expect(onLogout).toHaveBeenCalled();
    });
  });
});
