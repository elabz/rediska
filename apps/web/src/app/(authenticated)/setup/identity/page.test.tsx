import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import IdentitySetupPage from './page';

// Mock useRouter
const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    replace: vi.fn(),
    refresh: vi.fn(),
  }),
}));

describe('IdentitySetupPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(global.fetch).mockClear();
  });

  describe('rendering', () => {
    it('renders the setup page title', () => {
      render(<IdentitySetupPage />);

      expect(screen.getByRole('heading', { name: /set up your identity/i })).toBeInTheDocument();
    });

    it('renders description text', () => {
      render(<IdentitySetupPage />);

      expect(screen.getByText(/create your first identity/i)).toBeInTheDocument();
    });

    it('renders provider selection', () => {
      render(<IdentitySetupPage />);

      expect(screen.getByText(/select provider/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /reddit/i })).toBeInTheDocument();
    });

    it('renders identity form fields', () => {
      render(<IdentitySetupPage />);

      expect(screen.getByLabelText(/display name/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    });

    it('renders voice configuration section', () => {
      render(<IdentitySetupPage />);

      expect(screen.getByText(/voice configuration/i)).toBeInTheDocument();
    });

    it('renders submit button', () => {
      render(<IdentitySetupPage />);

      expect(screen.getByRole('button', { name: /create identity/i })).toBeInTheDocument();
    });
  });

  describe('provider selection', () => {
    it('highlights selected provider', async () => {
      const user = userEvent.setup();
      render(<IdentitySetupPage />);

      const redditButton = screen.getByRole('button', { name: /reddit/i });
      await user.click(redditButton);

      expect(redditButton).toHaveAttribute('data-selected', 'true');
    });
  });

  describe('form validation', () => {
    it('requires display name', async () => {
      const user = userEvent.setup();
      render(<IdentitySetupPage />);

      const displayNameInput = screen.getByLabelText(/display name/i);
      expect(displayNameInput).toBeRequired();
    });

    it('requires username', async () => {
      const user = userEvent.setup();
      render(<IdentitySetupPage />);

      const usernameInput = screen.getByLabelText(/username/i);
      expect(usernameInput).toBeRequired();
    });
  });

  describe('voice configuration', () => {
    it('renders tone selector', () => {
      render(<IdentitySetupPage />);

      expect(screen.getByLabelText(/tone/i)).toBeInTheDocument();
    });

    it('renders style selector', () => {
      render(<IdentitySetupPage />);

      expect(screen.getByLabelText(/style/i)).toBeInTheDocument();
    });

    it('renders persona name input', () => {
      render(<IdentitySetupPage />);

      expect(screen.getByLabelText(/persona name/i)).toBeInTheDocument();
    });

    it('renders custom system prompt textarea', () => {
      render(<IdentitySetupPage />);

      expect(screen.getByLabelText(/custom instructions/i)).toBeInTheDocument();
    });
  });

  describe('form submission', () => {
    it('shows loading state during submission', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch).mockImplementation(
        () => new Promise((resolve) => setTimeout(resolve, 1000))
      );

      render(<IdentitySetupPage />);

      // Fill required fields
      await user.click(screen.getByRole('button', { name: /reddit/i }));
      await user.type(screen.getByLabelText(/display name/i), 'Test Identity');
      await user.type(screen.getByLabelText(/username/i), 'testuser');

      await user.click(screen.getByRole('button', { name: /create identity/i }));

      expect(screen.getByRole('button', { name: /creating/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /creating/i })).toBeDisabled();
    });

    it('calls API with correct data', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ id: 1 }),
      } as Response);

      render(<IdentitySetupPage />);

      // Fill form
      await user.click(screen.getByRole('button', { name: /reddit/i }));
      await user.type(screen.getByLabelText(/display name/i), 'My Reddit Identity');
      await user.type(screen.getByLabelText(/username/i), 'my_reddit_user');
      await user.type(screen.getByLabelText(/persona name/i), 'Alex');

      await user.click(screen.getByRole('button', { name: /create identity/i }));

      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith('/api/core/identities', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: expect.stringContaining('my_reddit_user'),
        });
      });
    });

    it('redirects to inbox on success', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ id: 1 }),
      } as Response);

      render(<IdentitySetupPage />);

      await user.click(screen.getByRole('button', { name: /reddit/i }));
      await user.type(screen.getByLabelText(/display name/i), 'Test');
      await user.type(screen.getByLabelText(/username/i), 'testuser');

      await user.click(screen.getByRole('button', { name: /create identity/i }));

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith('/inbox');
      });
    });

    it('displays error on failure', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: false,
        json: () => Promise.resolve({ detail: 'Username already exists' }),
      } as Response);

      render(<IdentitySetupPage />);

      await user.click(screen.getByRole('button', { name: /reddit/i }));
      await user.type(screen.getByLabelText(/display name/i), 'Test');
      await user.type(screen.getByLabelText(/username/i), 'existinguser');

      await user.click(screen.getByRole('button', { name: /create identity/i }));

      await waitFor(() => {
        expect(screen.getByText(/username already exists/i)).toBeInTheDocument();
      });
    });
  });

  describe('OAuth connection', () => {
    it('renders connect button after provider selection', async () => {
      const user = userEvent.setup();
      render(<IdentitySetupPage />);

      // Connect button should not be visible initially
      expect(screen.queryByRole('button', { name: /connect.*reddit/i })).not.toBeInTheDocument();

      // Select provider
      await user.click(screen.getByRole('button', { name: /reddit/i }));

      // Now connect button should be visible
      expect(screen.getByRole('button', { name: /connect.*reddit/i })).toBeInTheDocument();
    });

    it('opens OAuth flow when connect is clicked', async () => {
      const user = userEvent.setup();
      // Mock window.open
      const mockOpen = vi.fn();
      vi.stubGlobal('open', mockOpen);

      render(<IdentitySetupPage />);

      await user.click(screen.getByRole('button', { name: /reddit/i }));
      await user.click(screen.getByRole('button', { name: /connect.*reddit/i }));

      expect(mockOpen).toHaveBeenCalledWith(
        expect.stringContaining('/api/core/providers/reddit/oauth/start'),
        expect.any(String),
        expect.any(String)
      );

      vi.unstubAllGlobals();
    });
  });
});
