import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LoginPage from './page';

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset window.location
    Object.defineProperty(window, 'location', {
      value: { href: '' },
      writable: true,
    });
  });

  describe('rendering', () => {
    it('renders the login form', () => {
      render(<LoginPage />);

      expect(screen.getByRole('heading', { name: /rediska/i })).toBeInTheDocument();
      expect(screen.getByText(/sign in to your account/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
    });

    it('renders username input with correct attributes', () => {
      render(<LoginPage />);

      const usernameInput = screen.getByLabelText(/username/i);
      expect(usernameInput).toHaveAttribute('type', 'text');
      expect(usernameInput).toBeRequired();
    });

    it('renders password input with correct attributes', () => {
      render(<LoginPage />);

      const passwordInput = screen.getByLabelText(/password/i);
      expect(passwordInput).toHaveAttribute('type', 'password');
      expect(passwordInput).toBeRequired();
    });
  });

  describe('user interactions', () => {
    it('allows user to type in username field', async () => {
      const user = userEvent.setup();
      render(<LoginPage />);

      const usernameInput = screen.getByLabelText(/username/i);
      await user.type(usernameInput, 'testuser');

      expect(usernameInput).toHaveValue('testuser');
    });

    it('allows user to type in password field', async () => {
      const user = userEvent.setup();
      render(<LoginPage />);

      const passwordInput = screen.getByLabelText(/password/i);
      await user.type(passwordInput, 'testpassword');

      expect(passwordInput).toHaveValue('testpassword');
    });
  });

  describe('form submission', () => {
    it('shows loading state during submission', async () => {
      const user = userEvent.setup();
      // Mock a slow response
      vi.mocked(global.fetch).mockImplementation(
        () => new Promise((resolve) => setTimeout(resolve, 1000))
      );

      render(<LoginPage />);

      await user.type(screen.getByLabelText(/username/i), 'testuser');
      await user.type(screen.getByLabelText(/password/i), 'testpassword');
      await user.click(screen.getByRole('button', { name: /sign in/i }));

      expect(screen.getByRole('button', { name: /signing in/i })).toBeInTheDocument();
      expect(screen.getByRole('button')).toBeDisabled();
    });

    it('calls login API with correct credentials', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ success: true }),
      } as Response);

      render(<LoginPage />);

      await user.type(screen.getByLabelText(/username/i), 'admin');
      await user.type(screen.getByLabelText(/password/i), 'password123');
      await user.click(screen.getByRole('button', { name: /sign in/i }));

      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith('/api/core/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: 'admin', password: 'password123' }),
          credentials: 'include',
        });
      });
    });

    it('redirects to inbox on successful login', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ success: true }),
      } as Response);

      render(<LoginPage />);

      await user.type(screen.getByLabelText(/username/i), 'admin');
      await user.type(screen.getByLabelText(/password/i), 'password123');
      await user.click(screen.getByRole('button', { name: /sign in/i }));

      await waitFor(() => {
        expect(window.location.href).toBe('/inbox');
      });
    });
  });

  describe('error handling', () => {
    it('displays error message on failed login', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: false,
        json: () => Promise.resolve({ detail: 'Invalid credentials' }),
      } as Response);

      render(<LoginPage />);

      await user.type(screen.getByLabelText(/username/i), 'wronguser');
      await user.type(screen.getByLabelText(/password/i), 'wrongpassword');
      await user.click(screen.getByRole('button', { name: /sign in/i }));

      await waitFor(() => {
        expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument();
      });
    });

    it('displays default error when no detail provided', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: false,
        json: () => Promise.resolve({}),
      } as Response);

      render(<LoginPage />);

      await user.type(screen.getByLabelText(/username/i), 'user');
      await user.type(screen.getByLabelText(/password/i), 'pass');
      await user.click(screen.getByRole('button', { name: /sign in/i }));

      await waitFor(() => {
        expect(screen.getByText(/login failed/i)).toBeInTheDocument();
      });
    });

    it('displays network error on fetch failure', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch).mockRejectedValueOnce(new Error('Network error'));

      render(<LoginPage />);

      await user.type(screen.getByLabelText(/username/i), 'user');
      await user.type(screen.getByLabelText(/password/i), 'pass');
      await user.click(screen.getByRole('button', { name: /sign in/i }));

      await waitFor(() => {
        expect(screen.getByText(/network error/i)).toBeInTheDocument();
      });
    });

    it('clears error when form is resubmitted', async () => {
      const user = userEvent.setup();
      // First call fails
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: false,
        json: () => Promise.resolve({ detail: 'First error' }),
      } as Response);
      // Second call succeeds
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ success: true }),
      } as Response);

      render(<LoginPage />);

      const usernameInput = screen.getByLabelText(/username/i);
      const passwordInput = screen.getByLabelText(/password/i);
      const submitButton = screen.getByRole('button', { name: /sign in/i });

      // First submission - fails
      await user.type(usernameInput, 'user');
      await user.type(passwordInput, 'pass');
      await user.click(submitButton);

      await waitFor(() => {
        expect(screen.getByText(/first error/i)).toBeInTheDocument();
      });

      // Second submission - error should be cleared during submission
      await user.click(submitButton);

      await waitFor(() => {
        expect(screen.queryByText(/first error/i)).not.toBeInTheDocument();
      });
    });

    it('re-enables button after failed login', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: false,
        json: () => Promise.resolve({ detail: 'Failed' }),
      } as Response);

      render(<LoginPage />);

      await user.type(screen.getByLabelText(/username/i), 'user');
      await user.type(screen.getByLabelText(/password/i), 'pass');
      await user.click(screen.getByRole('button', { name: /sign in/i }));

      await waitFor(() => {
        const button = screen.getByRole('button', { name: /sign in/i });
        expect(button).not.toBeDisabled();
      });
    });
  });

  describe('accessibility', () => {
    it('has accessible form labels', () => {
      render(<LoginPage />);

      const usernameInput = screen.getByLabelText(/username/i);
      const passwordInput = screen.getByLabelText(/password/i);

      expect(usernameInput).toHaveAttribute('id', 'username');
      expect(passwordInput).toHaveAttribute('id', 'password');
    });

    it('submit button has accessible name', () => {
      render(<LoginPage />);

      expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
    });
  });
});
