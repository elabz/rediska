import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  DiscoverTab,
  previewSearchUrl,
  type SourceCandidate,
  type SourceTrial,
} from './DiscoverTab';

// All candidates, locations and URLs below are synthetic.

function jsonResponse(body: unknown, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(body),
  } as Response);
}

function candidate(overrides: Partial<SourceCandidate> = {}): SourceCandidate {
  return {
    id: 1,
    kind: 'location',
    name: 'r/test_ropes',
    origin: 'mined',
    status: 'new',
    lift: 3.25,
    evidence_count: 6,
    evidence: { qualified_authors: 6, qualified_total: 8, analysed_authors: 9, analysed_total: 38 },
    snoozed_until: null,
    location_info: {
      name: 'r/test_ropes',
      description: 'Synthetic community description',
      member_count: 12000,
      active_count: 40,
      is_nsfw: true,
    },
    location_unavailable: false,
    watch_id: null,
    latest_trial: null,
    ...overrides,
  };
}

function trial(overrides: Partial<SourceTrial> = {}): SourceTrial {
  return {
    id: 7,
    candidate_id: 1,
    watch_id: 3,
    status: 'running',
    sample_size: 25,
    posts_total: 25,
    progress: 9,
    yield_report: null,
    error: null,
    ...overrides,
  };
}

function listResponse(items: SourceCandidate[], running: SourceTrial | null = null) {
  return { items, total: items.length, next_cursor: null, running_trial: running };
}

type Handler = (url: string, init?: RequestInit) => Promise<Response>;

function mockFetch(handler: Handler) {
  vi.mocked(global.fetch).mockImplementation(((input: RequestInfo | URL, init?: RequestInit) =>
    handler(String(input), init)) as typeof fetch);
}

describe('DiscoverTab', () => {
  beforeEach(() => {
    vi.mocked(global.fetch).mockReset();
  });

  it('shows a loading state', () => {
    mockFetch(() => new Promise(() => {}));

    render(<DiscoverTab onCreateWatch={vi.fn()} />);

    expect(screen.getByLabelText('Loading candidates')).toBeInTheDocument();
  });

  it('explains the empty state and keeps search usable', async () => {
    mockFetch(() => jsonResponse(listResponse([])));

    render(<DiscoverTab onCreateWatch={vi.fn()} />);

    expect(await screen.findByText('No candidate sources yet')).toBeInTheDocument();
    expect(screen.getByText(/enough analysed authors exist/)).toBeInTheDocument();
    expect(screen.getByLabelText('Search communities')).toBeEnabled();
  });

  it('shows an error state with retry', async () => {
    let calls = 0;
    mockFetch(() => {
      calls += 1;
      return calls === 1
        ? jsonResponse({ detail: 'Core unavailable' }, false, 500)
        : jsonResponse(listResponse([candidate()]));
    });

    render(<DiscoverTab onCreateWatch={vi.fn()} />);

    expect(await screen.findByText('Core unavailable')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Try Again' }));
    expect(await screen.findByText('r/test_ropes')).toBeInTheDocument();
  });

  it('renders evidence, location info, and trial yield', async () => {
    mockFetch(() =>
      jsonResponse(
        listResponse([
          candidate({
            status: 'trialled',
            latest_trial: trial({
              status: 'completed',
              progress: 25,
              yield_report: {
                posts_fetched: 25,
                skipped_empty: 2,
                link_only_resolved: 1,
                suitable: 4,
                needs_review: 6,
                not_recommended: 15,
                skipped_prior_verdict: 0,
                failed: 0,
                top_failing_gate: 'location',
                top_failing_gate_count: 9,
                median_post_age_hours: 5,
              },
            }),
          }),
          candidate({
            id: 2,
            kind: 'external_host',
            name: 'listings.example.test',
            lift: null,
            evidence: { occurrences: 12, example_urls: ['https://listings.example.test/ad/1'] },
            location_info: null,
          }),
        ]),
      ),
    );

    render(<DiscoverTab onCreateWatch={vi.fn()} />);

    const row = await screen.findByTestId('candidate-1');
    expect(within(row).getByText('lift 3.25×')).toBeInTheDocument();
    expect(within(row).getByText(/6 of 8 qualified authors/)).toBeInTheDocument();
    expect(within(row).getByText(/12k members/)).toBeInTheDocument();
    expect(within(row).getByText('NSFW')).toBeInTheDocument();
    const yieldBox = within(row).getByTestId('trial-yield');
    expect(yieldBox).toHaveTextContent('4 suitable');
    expect(yieldBox).toHaveTextContent('top failing gate: location (9)');

    const host = screen.getByTestId('candidate-2');
    expect(within(host).getByText(/12 distinct links seen/)).toBeInTheDocument();
    // An external host can never be trialled or turned into a watch.
    expect(within(host).queryByRole('button', { name: /trial/i })).not.toBeInTheDocument();
    expect(within(host).queryByRole('button', { name: /create watch/i })).not.toBeInTheDocument();
  });

  it('dismisses a candidate through the proxy', async () => {
    const posts: string[] = [];
    mockFetch((url, init) => {
      if (init?.method === 'POST') {
        posts.push(url);
        return jsonResponse({});
      }
      return jsonResponse(listResponse([candidate()]));
    });

    render(<DiscoverTab onCreateWatch={vi.fn()} />);
    const row = await screen.findByTestId('candidate-1');
    await userEvent.click(within(row).getByRole('button', { name: /dismiss/i }));

    await waitFor(() =>
      expect(posts).toContain('/api/core/source-candidates/1/dismiss'),
    );
  });

  it('starts a trial and hands create-watch to the page', async () => {
    const onCreateWatch = vi.fn();
    const posts: string[] = [];
    mockFetch((url, init) => {
      if (init?.method === 'POST') {
        posts.push(url);
        return jsonResponse({});
      }
      return jsonResponse(listResponse([candidate()]));
    });

    render(<DiscoverTab onCreateWatch={onCreateWatch} />);
    const row = await screen.findByTestId('candidate-1');
    await userEvent.click(within(row).getByRole('button', { name: /run trial/i }));
    await waitFor(() => expect(posts).toContain('/api/core/source-candidates/1/trial'));

    await userEvent.click(within(row).getByRole('button', { name: /create watch/i }));
    expect(onCreateWatch).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
  });

  it('shows trial progress with cancel, and blocks a second trial', async () => {
    const running = trial();
    const posts: string[] = [];
    mockFetch((url, init) => {
      if (init?.method === 'POST') {
        posts.push(url);
        return jsonResponse({});
      }
      return jsonResponse(
        listResponse(
          [candidate({ latest_trial: running }), candidate({ id: 2, name: 'r/test_other' })],
          running,
        ),
      );
    });

    render(<DiscoverTab onCreateWatch={vi.fn()} />);

    expect(await screen.findByTestId('trial-progress')).toHaveTextContent(
      'Trial: 9 of 25 posts analysed',
    );
    const other = screen.getByTestId('candidate-2');
    expect(within(other).getByRole('button', { name: /run trial/i })).toBeDisabled();

    await userEvent.click(within(screen.getByTestId('candidate-1')).getByRole('button', { name: /cancel/i }));
    await waitFor(() =>
      expect(posts).toContain('/api/core/source-candidates/trials/7/cancel'),
    );
  });

  it('restores from the dismissed view', async () => {
    const urls: string[] = [];
    mockFetch((url, init) => {
      urls.push(url);
      if (init?.method === 'POST') return jsonResponse({});
      return url.includes('status=dismissed')
        ? jsonResponse(listResponse([candidate({ status: 'dismissed' })]))
        : jsonResponse(listResponse([]));
    });

    render(<DiscoverTab onCreateWatch={vi.fn()} />);
    await screen.findByText('No candidate sources yet');
    await userEvent.click(screen.getByRole('button', { name: 'Dismissed' }));
    await userEvent.click(await screen.findByRole('button', { name: /restore/i }));

    await waitFor(() => expect(urls).toContain('/api/core/source-candidates/1/restore'));
  });

  it('searches and adds a location as a manual candidate', async () => {
    const bodies: Record<string, unknown>[] = [];
    mockFetch((url, init) => {
      if (url.startsWith('/api/core/source-candidates/search')) {
        return jsonResponse({
          query: 'rope',
          results: [
            { name: 'r/test_watched', is_nsfw: false, member_count: 10, watched: true,
              candidate_id: null, candidate_status: null },
            { name: 'r/test_fresh', is_nsfw: true, member_count: 500, watched: false,
              candidate_id: null, candidate_status: null },
          ],
        });
      }
      if (init?.method === 'POST') {
        bodies.push(JSON.parse(String(init.body)));
        return jsonResponse({ id: 9, status: 'new' });
      }
      return jsonResponse(listResponse([]));
    });

    render(<DiscoverTab onCreateWatch={vi.fn()} />);
    await screen.findByText('No candidate sources yet');
    await userEvent.type(screen.getByLabelText('Search communities'), 'rope');
    await userEvent.click(screen.getByRole('button', { name: 'Search' }));

    expect(await screen.findByText('Watched')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /add/i }));

    await waitFor(() => expect(bodies[0]).toMatchObject({ name: 'r/test_fresh' }));
    expect(await screen.findByText('Candidate (new)')).toBeInTheDocument();
  });

  it('builds a Browse deep link with the match string', () => {
    const url = previewSearchUrl('r/test_ropes', '(F4M OR F4A) AND (PA OR NJ)');
    const params = new URLSearchParams(url.split('?')[1]);

    expect(url.startsWith('/browse?')).toBe(true);
    expect(params.get('location')).toBe('r/test_ropes');
    expect(params.get('q')).toBe('(F4M OR F4A) AND (PA OR NJ)');
    expect(params.get('sort')).toBe('new');
  });

  it('opens Preview search in a new tab', async () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    mockFetch(() => jsonResponse(listResponse([candidate()])));

    render(<DiscoverTab onCreateWatch={vi.fn()} previewQuery="(F4M OR F4A)" />);
    const row = await screen.findByTestId('candidate-1');
    await userEvent.click(within(row).getByRole('button', { name: /preview search/i }));

    expect(open).toHaveBeenCalledWith(
      previewSearchUrl('r/test_ropes', '(F4M OR F4A)'),
      '_blank',
      'noopener',
    );
    open.mockRestore();
  });

  it('flags rule-restricted subreddits and hides them by default', async () => {
    const urls: string[] = [];
    mockFetch((url) => {
      urls.push(url);
      return jsonResponse(
        listResponse([
          candidate({
            contact_restricted: true,
            contact_rule: 'No personals: seeking meetups gets you banned',
          }),
        ]),
      );
    });

    render(<DiscoverTab onCreateWatch={vi.fn()} />);
    const row = await screen.findByTestId('candidate-1');

    expect(within(row).getByText('Rules forbid contact')).toBeInTheDocument();
    expect(within(row).getByTestId('contact-rule')).toHaveTextContent('No personals');
    expect(urls[0]).toContain('hide_restricted=true');

    await userEvent.click(screen.getByLabelText(/hide subreddits whose rules forbid/i));
    await waitFor(() => expect(urls.some((u) => !u.includes('hide_restricted'))).toBe(true));
  });

  it('filters candidates by name on the server', async () => {
    const urls: string[] = [];
    mockFetch((url) => {
      urls.push(url);
      return jsonResponse(listResponse([candidate()]));
    });

    render(<DiscoverTab onCreateWatch={vi.fn()} />);
    await screen.findByTestId('candidate-1');
    await userEvent.type(screen.getByLabelText('Filter candidates by name'), 'r4r{enter}');

    await waitFor(() => expect(urls.some((u) => u.includes('q=r4r'))).toBe(true));
  });
});
