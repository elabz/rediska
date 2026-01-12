import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { OnboardingGate } from './OnboardingGate';

// Mock useRouter
const mockPush = vi.fn();
const mockReplace = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    replace: mockReplace,
    refresh: vi.fn(),
  }),
  usePathname: () => '/inbox',
}));

describe('OnboardingGate', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(global.fetch).mockClear();
  });

  describe('loading state', () => {
    it('shows loading indicator while checking status', () => {
      vi.mocked(global.fetch).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      );

      render(
        <OnboardingGate>
          <div>Protected content</div>
        </OnboardingGate>
      );

      expect(screen.getByText(/loading/i)).toBeInTheDocument();
    });

    it('does not show children while loading', () => {
      vi.mocked(global.fetch).mockImplementation(
        () => new Promise(() => {})
      );

      render(
        <OnboardingGate>
          <div>Protected content</div>
        </OnboardingGate>
      );

      expect(screen.queryByText('Protected content')).not.toBeInTheDocument();
    });
  });

  describe('onboarding complete', () => {
    it('renders children when onboarding is complete', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ onboarding_complete: true, has_active_identity: true }),
      } as Response);

      render(
        <OnboardingGate>
          <div>Protected content</div>
        </OnboardingGate>
      );

      await waitFor(() => {
        expect(screen.getByText('Protected content')).toBeInTheDocument();
      });
    });

    it('does not redirect when onboarding is complete', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ onboarding_complete: true, has_active_identity: true }),
      } as Response);

      render(
        <OnboardingGate>
          <div>Protected content</div>
        </OnboardingGate>
      );

      await waitFor(() => {
        expect(screen.getByText('Protected content')).toBeInTheDocument();
      });

      expect(mockReplace).not.toHaveBeenCalled();
    });
  });

  describe('onboarding incomplete', () => {
    it('redirects to setup when no active identity', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ onboarding_complete: false, has_active_identity: false }),
      } as Response);

      render(
        <OnboardingGate>
          <div>Protected content</div>
        </OnboardingGate>
      );

      await waitFor(() => {
        expect(mockReplace).toHaveBeenCalledWith('/setup/identity');
      });
    });

    it('does not render children when redirecting', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ onboarding_complete: false, has_active_identity: false }),
      } as Response);

      render(
        <OnboardingGate>
          <div>Protected content</div>
        </OnboardingGate>
      );

      await waitFor(() => {
        expect(mockReplace).toHaveBeenCalled();
      });

      expect(screen.queryByText('Protected content')).not.toBeInTheDocument();
    });

    it('shows redirecting message', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ onboarding_complete: false, has_active_identity: false }),
      } as Response);

      render(
        <OnboardingGate>
          <div>Protected content</div>
        </OnboardingGate>
      );

      await waitFor(() => {
        expect(screen.getByText(/redirecting/i)).toBeInTheDocument();
      });
    });
  });

  describe('error handling', () => {
    it('shows error message on fetch failure', async () => {
      vi.mocked(global.fetch).mockRejectedValueOnce(new Error('Network error'));

      render(
        <OnboardingGate>
          <div>Protected content</div>
        </OnboardingGate>
      );

      await waitFor(() => {
        expect(screen.getByText(/error/i)).toBeInTheDocument();
      });
    });

    it('provides retry option on error', async () => {
      vi.mocked(global.fetch).mockRejectedValueOnce(new Error('Network error'));

      render(
        <OnboardingGate>
          <div>Protected content</div>
        </OnboardingGate>
      );

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
      });
    });

    it('does not render children on error', async () => {
      vi.mocked(global.fetch).mockRejectedValueOnce(new Error('Network error'));

      render(
        <OnboardingGate>
          <div>Protected content</div>
        </OnboardingGate>
      );

      await waitFor(() => {
        expect(screen.getByText(/error/i)).toBeInTheDocument();
      });

      expect(screen.queryByText('Protected content')).not.toBeInTheDocument();
    });
  });

  describe('fallback prop', () => {
    it('renders custom loading fallback', () => {
      vi.mocked(global.fetch).mockImplementation(
        () => new Promise(() => {})
      );

      render(
        <OnboardingGate loadingFallback={<div>Custom loading...</div>}>
          <div>Protected content</div>
        </OnboardingGate>
      );

      expect(screen.getByText('Custom loading...')).toBeInTheDocument();
    });
  });

  describe('accessibility', () => {
    it('has accessible loading state', () => {
      vi.mocked(global.fetch).mockImplementation(
        () => new Promise(() => {})
      );

      render(
        <OnboardingGate>
          <div>Protected content</div>
        </OnboardingGate>
      );

      expect(screen.getByRole('status')).toBeInTheDocument();
    });
  });
});
