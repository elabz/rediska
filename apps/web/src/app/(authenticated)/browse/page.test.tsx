import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import BrowsePage from './page';

// Synthetic location and query only.

describe('BrowsePage deep link', () => {
  beforeEach(() => {
    vi.mocked(global.fetch).mockReset();
    vi.mocked(global.fetch).mockImplementation((() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ posts: [], cursor: null, identities: [] }),
      } as Response)) as typeof fetch);
  });

  afterEach(() => {
    window.history.replaceState(null, '', '/');
  });

  it('runs the search from location/q/sort/t URL parameters on load', async () => {
    window.history.replaceState(
      null,
      '',
      '/browse?location=r%2Ftest_sub&q=%28F4M+OR+F4A%29&sort=new&t=month',
    );

    render(<BrowsePage />);

    await waitFor(() => {
      const urls = vi.mocked(global.fetch).mock.calls.map((c) => String(c[0]));
      const browse = urls.find((u) => u.includes('/api/core/sources/reddit/locations/test_sub/posts'));
      expect(browse).toBeDefined();
      const params = new URLSearchParams(browse!.split('?')[1]);
      expect(params.get('q')).toBe('(F4M OR F4A)');
      expect(params.get('sort')).toBe('new');
      expect(params.get('t')).toBe('month');
    });
  });

  it('does not search without a location parameter', async () => {
    render(<BrowsePage />);

    await new Promise((r) => setTimeout(r, 50));
    const urls = vi.mocked(global.fetch).mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes('/locations/'))).toBe(false);
  });
});
