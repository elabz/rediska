import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CopyBadge } from './CopyBadge';
import { CopyClusterDrawer } from './CopyClusterDrawer';
import { CopyClusterPanel } from './CopyClusterPanel';
import { CopyClustersTab } from './CopyClustersTab';
import type { CopyClusterDetail, CopyClusterSummary, CopyInfo } from '@/lib/copyClusters';

const COPY: CopyInfo = {
  cluster_id: 5,
  kind: 'ring_suspect',
  computed_kind: 'ring_suspect',
  decision: null,
  author_count: 3,
  earliest_other_posted_at: '2026-09-01T12:00:00',
};

const SUMMARY: CopyClusterSummary = {
  id: 5,
  provider_id: 'reddit',
  kind: 'ring_suspect',
  computed_kind: 'ring_suspect',
  decision: null,
  decision_notes: null,
  decided_at: null,
  author_count: 3,
  member_count: 3,
  first_posted_at: '2026-09-01T12:00:00',
  last_posted_at: '2026-09-03T12:00:00',
  created_at: '2026-09-03T12:00:00',
};

function member(i: number, name: string, extra: Partial<CopyClusterDetail['members'][0]> = {}) {
  return {
    member_id: i,
    fingerprint_id: i,
    external_post_id: `test_p${i}`,
    author_username: name,
    account_id: i * 10,
    remote_status: 'active',
    posted_at: `2026-09-0${i}T12:00:00`,
    first_seen_at: `2026-09-0${i}T12:00:00`,
    location: 'r/test',
    source: 'scout',
    char_len: 900,
    similarity: 1,
    repost_of_id: null,
    lead_id: null,
    lead_status: null,
    scout_post_id: null,
    scout_watch_id: null,
    analysis_id: null,
    recommendation: null,
    human_verdict: null,
    ban_id: null,
    ban_status: null,
    ...extra,
  };
}

const DETAIL: CopyClusterDetail = {
  cluster: SUMMARY,
  members: [
    member(1, 'test_first', { lead_id: 3, lead_status: 'ignored', recommendation: 'not_recommended' }),
    member(2, 'test_second', { human_verdict: 'agree' }),
    member(3, 'test_third'),
  ],
};

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response);
}

type FetchArgs = [url: string, init?: RequestInit];
let fetchMock: Mock<FetchArgs, Promise<Response>>;
let listBody: unknown;

beforeEach(() => {
  listBody = { items: [SUMMARY], next_cursor: null };
  fetchMock = vi.fn<FetchArgs, Promise<Response>>((url, init) => {
    if (url.startsWith('/api/core/ban-list/status')) {
      return jsonResponse({ banned: false, entry: null });
    }
    if (url === '/api/core/ban-list/bulk') {
      return jsonResponse({ cluster_id: 5, banned: [{}, {}] });
    }
    if (url.endsWith('/decision')) {
      const body = JSON.parse(String(init?.body));
      return jsonResponse({ ...SUMMARY, decision: body.decision, kind: body.decision });
    }
    if (url === '/api/core/copy-clusters/5') return jsonResponse(DETAIL);
    if (url.startsWith('/api/core/copy-clusters?')) return jsonResponse(listBody);
    return jsonResponse({ detail: 'unexpected' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function calls(pattern: string) {
  return fetchMock.mock.calls.filter(([url]) => String(url).includes(pattern));
}

describe('CopyBadge', () => {
  it('renders nothing without a cluster', () => {
    const { container } = render(<CopyBadge copy={null} />);
    expect(container.innerHTML).toBe('');
  });

  it('shows kind and author count, and opens the drawer on click', async () => {
    render(<CopyBadge copy={COPY} externalPostId="test_p2" />);
    const badge = screen.getByTestId('copy-badge');
    expect(badge.textContent).toContain('Ring suspect');
    expect(badge.textContent).toContain('3 authors');

    await userEvent.click(badge);
    await waitFor(() => expect(screen.getAllByTestId('copy-member')).toHaveLength(3));
    expect(screen.getByText('this post')).toBeTruthy();
    expect(screen.getByText('earliest poster')).toBeTruthy();
  });
});

describe('CopyClusterDrawer', () => {
  it('lists what we hold per author', async () => {
    render(<CopyClusterDrawer clusterId={5} open onOpenChange={() => {}} />);
    await waitFor(() => expect(screen.getAllByTestId('copy-member')).toHaveLength(3));
    expect(screen.getByText(/Lead #3/).textContent).toContain('ignored');
    expect(screen.getByText('not recommended')).toBeTruthy();
    expect(screen.getByText('you: agree')).toBeTruthy();
  });

  it('asks for confirmation before dissolving as a coincidence', async () => {
    const onChanged = vi.fn();
    render(<CopyClusterDrawer clusterId={5} open onOpenChange={() => {}} onChanged={onChanged} />);
    await waitFor(() => screen.getAllByTestId('copy-member'));

    await userEvent.click(screen.getByRole('button', { name: 'Coincidence' }));
    expect(calls('/decision')).toHaveLength(0);
    await userEvent.click(screen.getByRole('button', { name: /confirm: dissolve/i }));
    await waitFor(() => expect(calls('/decision')).toHaveLength(1));
    expect(JSON.parse(String(calls('/decision')[0][1].body))).toEqual({
      decision: 'coincidence',
      notes: null,
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it('records a confirmed ring in one click', async () => {
    render(<CopyClusterDrawer clusterId={5} open onOpenChange={() => {}} />);
    await waitFor(() => screen.getAllByTestId('copy-member'));
    await userEvent.click(screen.getByRole('button', { name: 'Confirmed ring' }));
    await waitFor(() => expect(calls('/decision')).toHaveLength(1));
  });

  it('bans the cluster without the earliest poster, after confirmation', async () => {
    render(<CopyClusterDrawer clusterId={5} open onOpenChange={() => {}} />);
    await waitFor(() => screen.getAllByTestId('copy-member'));

    await userEvent.click(screen.getByRole('button', { name: /ban cluster \(2\)/i }));
    expect(calls('/ban-list/bulk')).toHaveLength(0);
    await userEvent.click(screen.getByRole('button', { name: /confirm: ban 2/i }));
    await waitFor(() => expect(calls('/ban-list/bulk')).toHaveLength(1));
    expect(JSON.parse(String(calls('/ban-list/bulk')[0][1].body))).toMatchObject({
      cluster_id: 5,
      reason: 'copy_ring',
      exclude_usernames: ['test_first'],
    });
  });

  it('shows an error state with retry', async () => {
    fetchMock.mockImplementation(() => jsonResponse({ detail: 'Copy cluster 5 not found' }, 404));
    render(<CopyClusterDrawer clusterId={5} open onOpenChange={() => {}} />);
    expect(await screen.findByText('Copy cluster 5 not found')).toBeTruthy();
    expect(screen.getByRole('button', { name: /try again/i })).toBeTruthy();
  });
});

describe('CopyClusterPanel', () => {
  it('lists the other authors, not this post', async () => {
    render(<CopyClusterPanel copy={COPY} externalPostId="test_p2" />);
    await waitFor(() => expect(screen.getAllByTestId('copy-member')).toHaveLength(2));
    expect(screen.queryByText('u/test_second')).toBeNull();
    expect(screen.getByText('u/test_first')).toBeTruthy();
  });
});

describe('CopyClustersTab', () => {
  it('lists undecided clusters by default', async () => {
    render(<CopyClustersTab />);
    await waitFor(() => expect(screen.getAllByTestId('copy-cluster-row')).toHaveLength(1));
    const url = String(calls('/api/core/copy-clusters?')[0][0]);
    expect(url).toContain('decision=none');
    // Spam rings are handled automatically; the tab lists the rest by default.
    expect(url).toContain('handled=false');
  });

  it('shows an empty state', async () => {
    listBody = { items: [], next_cursor: null };
    render(<CopyClustersTab />);
    expect(await screen.findByText('No copy clusters')).toBeTruthy();
  });

  it('shows an error state with retry', async () => {
    fetchMock.mockImplementation(() => jsonResponse({ detail: 'boom' }, 500));
    render(<CopyClustersTab />);
    expect(await screen.findByText('boom')).toBeTruthy();
    expect(screen.getByRole('button', { name: /try again/i })).toBeTruthy();
  });

  it('opens a cluster from its row', async () => {
    render(<CopyClustersTab />);
    await userEvent.click(await screen.findByTestId('copy-cluster-row'));
    await waitFor(() => expect(screen.getAllByTestId('copy-member')).toHaveLength(3));
  });
});
