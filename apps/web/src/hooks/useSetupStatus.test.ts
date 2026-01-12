import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useSetupStatus } from './useSetupStatus';

describe('useSetupStatus', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(global.fetch).mockClear();
  });

  describe('initial state', () => {
    it('returns loading true initially', () => {
      vi.mocked(global.fetch).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      );

      const { result } = renderHook(() => useSetupStatus());

      expect(result.current.loading).toBe(true);
    });

    it('returns null status initially', () => {
      vi.mocked(global.fetch).mockImplementation(
        () => new Promise(() => {})
      );

      const { result } = renderHook(() => useSetupStatus());

      expect(result.current.status).toBeNull();
    });

    it('returns no error initially', () => {
      vi.mocked(global.fetch).mockImplementation(
        () => new Promise(() => {})
      );

      const { result } = renderHook(() => useSetupStatus());

      expect(result.current.error).toBeNull();
    });
  });

  describe('successful fetch', () => {
    it('fetches from /api/core/setup/status', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ onboarding_complete: true, has_active_identity: true }),
      } as Response);

      renderHook(() => useSetupStatus());

      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith('/api/core/setup/status', {
          credentials: 'include',
        });
      });
    });

    it('returns onboarding complete status', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ onboarding_complete: true, has_active_identity: true }),
      } as Response);

      const { result } = renderHook(() => useSetupStatus());

      await waitFor(() => {
        expect(result.current.status?.onboarding_complete).toBe(true);
      });
    });

    it('returns has_active_identity flag', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ onboarding_complete: true, has_active_identity: true }),
      } as Response);

      const { result } = renderHook(() => useSetupStatus());

      await waitFor(() => {
        expect(result.current.status?.has_active_identity).toBe(true);
      });
    });

    it('returns incomplete onboarding when no identity', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ onboarding_complete: false, has_active_identity: false }),
      } as Response);

      const { result } = renderHook(() => useSetupStatus());

      await waitFor(() => {
        expect(result.current.status?.onboarding_complete).toBe(false);
        expect(result.current.status?.has_active_identity).toBe(false);
      });
    });

    it('sets loading to false after fetch', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ onboarding_complete: true, has_active_identity: true }),
      } as Response);

      const { result } = renderHook(() => useSetupStatus());

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });
    });
  });

  describe('fetch error', () => {
    it('sets error on network failure', async () => {
      vi.mocked(global.fetch).mockRejectedValueOnce(new Error('Network error'));

      const { result } = renderHook(() => useSetupStatus());

      await waitFor(() => {
        expect(result.current.error).toBe('Failed to check setup status');
      });
    });

    it('sets error on non-ok response', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: false,
        status: 500,
      } as Response);

      const { result } = renderHook(() => useSetupStatus());

      await waitFor(() => {
        expect(result.current.error).toBe('Failed to check setup status');
      });
    });

    it('sets loading to false on error', async () => {
      vi.mocked(global.fetch).mockRejectedValueOnce(new Error('Network error'));

      const { result } = renderHook(() => useSetupStatus());

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });
    });

    it('keeps status null on error', async () => {
      vi.mocked(global.fetch).mockRejectedValueOnce(new Error('Network error'));

      const { result } = renderHook(() => useSetupStatus());

      await waitFor(() => {
        expect(result.current.status).toBeNull();
      });
    });
  });

  describe('refetch', () => {
    it('provides refetch function', async () => {
      vi.mocked(global.fetch).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ onboarding_complete: false, has_active_identity: false }),
      } as Response);

      const { result } = renderHook(() => useSetupStatus());

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(typeof result.current.refetch).toBe('function');
    });

    it('refetches status when called', async () => {
      vi.mocked(global.fetch)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ onboarding_complete: false, has_active_identity: false }),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ onboarding_complete: true, has_active_identity: true }),
        } as Response);

      const { result } = renderHook(() => useSetupStatus());

      await waitFor(() => {
        expect(result.current.status?.onboarding_complete).toBe(false);
      });

      result.current.refetch();

      await waitFor(() => {
        expect(result.current.status?.onboarding_complete).toBe(true);
      });
    });
  });
});
