import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BanDialog } from './BanDialog';
import { BannedBanner } from './BannedBanner';
import { BannedView } from './BannedView';
import { BanSuggestions } from './BanSuggestions';
import { bannedDetail, errorMessage, normalizeUsername, type BanEntry } from '@/lib/banList';

const ENTRY: BanEntry = {
  id: 7,
  provider_id: 'reddit',
  username: 'test_banned',
  reason: 'scam',
  notes: 'sent a payment link',
  source: 'manual',
  status: 'active',
  cluster_id: null,
  created_by: 'user',
  created_at: '2026-09-18T00:00:00Z',
  lifted_at: null,
  account_id: 12,
  lead_ids: [3, 4],
};

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response);
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('banList helpers', () => {
  it('recognises the 409 counterpart_banned detail and nothing else', () => {
    expect(bannedDetail({ detail: { code: 'counterpart_banned', message: 'm', username: 'x', ban_id: 1 } }))
      .toMatchObject({ username: 'x' });
    expect(bannedDetail({ detail: 'Conversation not found' })).toBeNull();
    expect(bannedDetail(null)).toBeNull();
  });

  it('reads a message from string or structured detail', () => {
    expect(errorMessage({ detail: 'plain' }, 'fb')).toBe('plain');
    expect(errorMessage({ detail: { message: 'structured' } }, 'fb')).toBe('structured');
    expect(errorMessage(null, 'fb')).toBe('fb');
  });

  it('strips a u/ prefix', () => {
    expect(normalizeUsername(' u/Test_User ')).toBe('Test_User');
    expect(normalizeUsername('/u/test_user')).toBe('test_user');
  });
});

describe('BanDialog', () => {
  it('requires a reason before banning', async () => {
    render(<BanDialog open onOpenChange={() => {}} username="test_user" />);
    expect(screen.getByRole('button', { name: /^ban$/i })).toBeDisabled();
  });

  it('posts the chosen reason and notes and reports the result', async () => {
    const user = userEvent.setup();
    const onBanned = vi.fn();
    const onOpenChange = vi.fn();
    fetchMock.mockReturnValueOnce(
      jsonResponse({ entry: ENTRY, created: true, reactivated: false, leads_withdrawn: [3] }, 201),
    );

    render(
      <BanDialog open onOpenChange={onOpenChange} username="test_banned" onBanned={onBanned} />,
    );
    await user.click(screen.getByRole('radio', { name: /scam/i }));
    await user.type(screen.getByLabelText(/notes/i), 'payment link');
    await user.click(screen.getByRole('button', { name: /^ban$/i }));

    await waitFor(() => expect(onBanned).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/core/ban-list');
    expect(JSON.parse(init.body)).toMatchObject({
      username: 'test_banned',
      reason: 'scam',
      notes: 'payment link',
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('shows the API error and stays open', async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    fetchMock.mockReturnValueOnce(jsonResponse({ detail: 'A reason is required' }, 400));

    render(<BanDialog open onOpenChange={onOpenChange} username="test_user" />);
    await user.click(screen.getByRole('radio', { name: /hostile/i }));
    await user.click(screen.getByRole('button', { name: /^ban$/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent('A reason is required');
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });
});

describe('BannedBanner', () => {
  it('shows reason and date and lifts on click', async () => {
    const user = userEvent.setup();
    const onLift = vi.fn();
    render(<BannedBanner entry={ENTRY} onLift={onLift} message="nothing can be sent" />);
    expect(screen.getByRole('status')).toHaveTextContent('u/test_banned is banned');
    expect(screen.getByRole('status')).toHaveTextContent('Scam / seller');
    expect(screen.getByText('nothing can be sent')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /lift ban/i }));
    expect(onLift).toHaveBeenCalled();
  });
});

describe('BannedView', () => {
  it('shows the empty state when nobody is banned', async () => {
    fetchMock.mockReturnValue(jsonResponse({ items: [], next_cursor: null }));
    render(<BannedView />);
    expect(await screen.findByText('Nobody is banned')).toBeInTheDocument();
    expect(screen.getByText(/ban an account from its conversation/i)).toBeInTheDocument();
  });

  it('shows an error state with retry', async () => {
    fetchMock.mockReturnValueOnce(jsonResponse({ detail: 'Failed to fetch ban list' }, 500));
    render(<BannedView />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to fetch ban list');
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });

  it('lists entries with links and lifts one', async () => {
    const user = userEvent.setup();
    fetchMock.mockReturnValueOnce(jsonResponse({ items: [ENTRY], next_cursor: null }));
    render(<BannedView />);

    const row = await screen.findByTestId('ban-row');
    expect(row).toHaveTextContent('u/test_banned');
    expect(row).toHaveTextContent('sent a payment link');
    expect(screen.getByRole('link', { name: 'u/test_banned' })).toHaveAttribute('href', '/profile/12');
    expect(screen.getByRole('link', { name: '#3' })).toHaveAttribute('href', '/leads/3');

    fetchMock.mockReturnValueOnce(
      jsonResponse({ entry: { ...ENTRY, status: 'lifted' }, leads_restored: [3, 4] }),
    );
    await user.click(screen.getByRole('button', { name: /^lift$/i }));
    await waitFor(() => expect(screen.queryByTestId('ban-row')).not.toBeInTheDocument());
    expect(fetchMock.mock.calls[1][0]).toBe('/api/core/ban-list/7/lift');
  });

  it('passes the search query to the API', async () => {
    const user = userEvent.setup();
    fetchMock.mockReturnValue(jsonResponse({ items: [], next_cursor: null }));
    render(<BannedView />);
    await screen.findByText('Nobody is banned');
    await user.type(screen.getByLabelText('Search bans'), 'scam{Enter}');
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes('q=scam'))).toBe(true),
    );
  });
});

describe('BanSuggestions', () => {
  it('explains the empty queue when copy detection is not installed', async () => {
    fetchMock.mockReturnValueOnce(jsonResponse({ available: false, items: [] }));
    render(<BanSuggestions />);
    expect(await screen.findByTestId('ban-suggestions-empty')).toHaveTextContent(
      /once copy detection is installed/i,
    );
  });

  it('bulk-bans a cluster excluding the earliest poster by default', async () => {
    const user = userEvent.setup();
    fetchMock.mockReturnValueOnce(
      jsonResponse({
        available: true,
        items: [
          {
            cluster_id: 9,
            kind: 'ring_suspect',
            suggested_usernames: ['test_a', 'test_b', 'test_c'],
            authors: ['test_a', 'test_b', 'test_c'].map((u, i) => ({
              username: u,
              account_id: null,
              remote_status: 'active',
              first_posted_at: `2026-09-1${i}T00:00:00Z`,
              post_count: 1,
              banned: false,
              dismissed: false,
              earliest: i === 0,
            })),
          },
        ],
      }),
    );
    render(<BanSuggestions />);
    expect(await screen.findByText('earliest poster')).toBeInTheDocument();

    fetchMock.mockReturnValueOnce(jsonResponse({ cluster_id: 9, banned: [] }));
    fetchMock.mockReturnValueOnce(jsonResponse({ available: true, items: [] }));
    await user.click(screen.getByRole('button', { name: /ban 2 selected/i }));

    await waitFor(() => expect(fetchMock.mock.calls[1][0]).toBe('/api/core/ban-list/bulk'));
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({
      cluster_id: 9,
      reason: 'copy_ring',
      exclude_usernames: ['test_a'],
    });
  });
});
