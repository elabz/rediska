import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import IdentitiesPage from './page';

// Mock useRouter
const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    replace: vi.fn(),
    refresh: vi.fn(),
  }),
}));

const mockIdentities = [
  {
    id: 1,
    display_name: 'Main Reddit Account',
    provider_id: 'reddit',
    external_username: 'test_user',
    is_active: true,
    voice_config_json: {
      tone: 'professional',
      style: 'concise',
      persona_name: 'Alex',
    },
    created_at: '2024-01-15T10:00:00Z',
  },
  {
    id: 2,
    display_name: 'Secondary Account',
    provider_id: 'reddit',
    external_username: 'other_user',
    is_active: false,
    voice_config_json: null,
    created_at: '2024-01-10T08:00:00Z',
  },
];

describe('IdentitiesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(global.fetch).mockClear();
  });

  describe('loading state', () => {
    it('shows loading state while fetching identities', () => {
      vi.mocked(global.fetch).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      );

      render(<IdentitiesPage />);

      expect(screen.getByText(/loading/i)).toBeInTheDocument();
    });
  });

  describe('rendering identities', () => {
    it('renders page title', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockIdentities),
      } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /identities/i })).toBeInTheDocument();
      });
    });

    it('renders list of identities', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockIdentities),
      } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByText('Main Reddit Account')).toBeInTheDocument();
        expect(screen.getByText('Secondary Account')).toBeInTheDocument();
      });
    });

    it('shows provider for each identity', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockIdentities),
      } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        const providerBadges = screen.getAllByText(/reddit/i);
        expect(providerBadges.length).toBeGreaterThanOrEqual(2);
      });
    });

    it('shows username for each identity', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockIdentities),
      } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByText(/test_user/)).toBeInTheDocument();
        expect(screen.getByText(/other_user/)).toBeInTheDocument();
      });
    });

    it('shows active/inactive status', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockIdentities),
      } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByText('Active')).toBeInTheDocument();
        expect(screen.getByText('Inactive')).toBeInTheDocument();
      });
    });

    it('shows empty state when no identities', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve([]),
      } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByText(/no identities/i)).toBeInTheDocument();
      });
    });
  });

  describe('add identity button', () => {
    it('renders add identity button', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockIdentities),
      } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /add identity/i })).toBeInTheDocument();
      });
    });

    it('navigates to setup page when add button clicked', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockIdentities),
      } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /add identity/i })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /add identity/i }));

      expect(mockPush).toHaveBeenCalledWith('/setup/identity');
    });
  });

  describe('edit identity', () => {
    it('renders edit button for each identity', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockIdentities),
      } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        const editButtons = screen.getAllByRole('button', { name: /edit/i });
        expect(editButtons.length).toBe(2);
      });
    });

    it('opens edit modal when edit button clicked', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockIdentities),
      } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByText('Main Reddit Account')).toBeInTheDocument();
      });

      const editButtons = screen.getAllByRole('button', { name: /edit/i });
      await user.click(editButtons[0]);

      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(screen.getByLabelText(/display name/i)).toHaveValue('Main Reddit Account');
    });

    it('populates edit form with identity data', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockIdentities),
      } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByText('Main Reddit Account')).toBeInTheDocument();
      });

      const editButtons = screen.getAllByRole('button', { name: /edit/i });
      await user.click(editButtons[0]);

      expect(screen.getByLabelText(/persona name/i)).toHaveValue('Alex');
    });

    it('saves edited identity', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockIdentities),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ ...mockIdentities[0], display_name: 'Updated Name' }),
        } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByText('Main Reddit Account')).toBeInTheDocument();
      });

      const editButtons = screen.getAllByRole('button', { name: /edit/i });
      await user.click(editButtons[0]);

      const displayNameInput = screen.getByLabelText(/display name/i);
      await user.clear(displayNameInput);
      await user.type(displayNameInput, 'Updated Name');

      await user.click(screen.getByRole('button', { name: /save/i }));

      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith('/api/core/identities/1', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: expect.stringContaining('Updated Name'),
        });
      });
    });

    it('closes modal after successful save', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockIdentities),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ ...mockIdentities[0], display_name: 'Updated Name' }),
        } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByText('Main Reddit Account')).toBeInTheDocument();
      });

      const editButtons = screen.getAllByRole('button', { name: /edit/i });
      await user.click(editButtons[0]);

      await user.click(screen.getByRole('button', { name: /save/i }));

      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });
    });

    it('shows error on save failure', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockIdentities),
        } as Response)
        .mockResolvedValueOnce({
          ok: false,
          json: () => Promise.resolve({ detail: 'Failed to update' }),
        } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByText('Main Reddit Account')).toBeInTheDocument();
      });

      const editButtons = screen.getAllByRole('button', { name: /edit/i });
      await user.click(editButtons[0]);

      await user.click(screen.getByRole('button', { name: /save/i }));

      await waitFor(() => {
        expect(screen.getByText(/failed to update/i)).toBeInTheDocument();
      });
    });
  });

  describe('toggle identity status', () => {
    it('renders toggle button for each identity', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockIdentities),
      } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Deactivate' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Activate' })).toBeInTheDocument();
      });
    });

    it('deactivates active identity', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockIdentities),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ ...mockIdentities[0], is_active: false }),
        } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Deactivate' })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: 'Deactivate' }));

      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith('/api/core/identities/1', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ is_active: false }),
        });
      });
    });

    it('activates inactive identity', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockIdentities),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ ...mockIdentities[1], is_active: true }),
        } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Activate' })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: 'Activate' }));

      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith('/api/core/identities/2', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ is_active: true }),
        });
      });
    });
  });

  describe('error handling', () => {
    it('shows error when fetch fails', async () => {
      vi.mocked(global.fetch).mockRejectedValueOnce(new Error('Network error'));

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByText(/failed to load/i)).toBeInTheDocument();
      });
    });

    it('shows retry button on error', async () => {
      vi.mocked(global.fetch).mockRejectedValueOnce(new Error('Network error'));

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
      });
    });

    it('retries fetch when retry button clicked', async () => {
      const user = userEvent.setup();
      vi.mocked(global.fetch)
        .mockRejectedValueOnce(new Error('Network error'))
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockIdentities),
        } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /retry/i }));

      await waitFor(() => {
        expect(screen.getByText('Main Reddit Account')).toBeInTheDocument();
      });
    });
  });

  describe('voice configuration display', () => {
    it('shows voice config details in list', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockIdentities),
      } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByText(/professional/i)).toBeInTheDocument();
        expect(screen.getByText(/concise/i)).toBeInTheDocument();
      });
    });

    it('shows no voice config message for identities without config', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve([mockIdentities[1]]),
      } as Response);

      render(<IdentitiesPage />);

      await waitFor(() => {
        expect(screen.getByText(/no voice config/i)).toBeInTheDocument();
      });
    });
  });
});
