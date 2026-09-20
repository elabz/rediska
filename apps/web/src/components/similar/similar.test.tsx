import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SimilarButton, SimilarPanel } from './SimilarPanel';
import { RewriteSuggestions } from './RewriteSuggestions';
import type { SimilarHit, SimilarResponse } from '@/lib/similar';

function hit(id: string, overrides: Partial<SimilarHit> = {}): SimilarHit {
  return {
    id,
    doc_type: 'lead_post',
    entity_id: Number(id.split(':')[1]),
    score: 0.98,
    similarity: 0.96,
    title: 'test_title',
    excerpt: 'test excerpt',
    author_username: 'test_author',
    account_id: 7,
    location: 'test_sub',
    created_at: '2026-09-01T12:00:00',
    post_url: null,
    lead_status: 'ignored',
    recommendation: 'not_recommended',
    priority: null,
    compatibility_score: null,
    human_verdict: null,
    author_banned: false,
    ...overrides,
  };
}

const VECTOR_RESPONSE: SimilarResponse = {
  method: 'vector',
  min_score: 0.8,
  source: { doc_type: 'lead_post', entity_id: 1, author_username: 'test_me' },
  results: [hit('lead_post:2')],
};

const SUGGESTION = {
  id: 11,
  provider_id: 'reddit',
  source_doc_type: 'lead_post',
  source_entity_id: 1,
  source_external_post_id: 'test_post_a',
  source_author: 'test_me',
  match_doc_type: 'lead_post',
  match_entity_id: 2,
  match_external_post_id: 'test_post_b',
  match_author: 'test_other',
  similarity: 0.96,
  status: 'new',
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
let similarBody: unknown;
let similarStatus: number;
let suggestionItems: unknown[];

beforeEach(() => {
  similarBody = VECTOR_RESPONSE;
  similarStatus = 200;
  suggestionItems = [SUGGESTION];
  fetchMock = vi.fn<FetchArgs, Promise<Response>>((url) => {
    if (url === '/api/core/similar') return jsonResponse(similarBody, similarStatus);
    if (String(url).includes('/api/core/copy-suggestions/')) {
      return jsonResponse({ suggestion: SUGGESTION, message: 'Recorded.' });
    }
    if (String(url).startsWith('/api/core/copy-suggestions')) {
      return jsonResponse({ items: suggestionItems });
    }
    return jsonResponse({ detail: 'unexpected' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('SimilarPanel', () => {
  it('lists neighbours with what became of them', async () => {
    render(
      <SimilarPanel docType="lead_post" entityId={1} open onOpenChange={() => {}} />,
    );

    await waitFor(() => expect(screen.getByTestId('similar-hit')).toBeInTheDocument());
    expect(screen.getByText('96% alike')).toBeInTheDocument();
    expect(screen.getByText('ignored')).toBeInTheDocument();
  });

  it('says when the match was words, not meaning', async () => {
    similarBody = { ...VECTOR_RESPONSE, method: 'text', results: [hit('lead_post:2', { similarity: null })] };

    render(
      <SimilarPanel docType="lead_post" entityId={1} open onOpenChange={() => {}} />,
    );

    await waitFor(() =>
      expect(screen.getByTestId('similar-text-notice')).toBeInTheDocument(),
    );
  });

  it('has an empty state rather than a blank panel', async () => {
    similarBody = { ...VECTOR_RESPONSE, results: [] };

    render(
      <SimilarPanel docType="lead_post" entityId={1} open onOpenChange={() => {}} />,
    );

    await waitFor(() => expect(screen.getByTestId('similar-empty')).toBeInTheDocument());
  });

  it('shows an error with a retry rather than an empty list', async () => {
    similarBody = { detail: { error: 'Elasticsearch is down' } };
    similarStatus = 503;

    render(
      <SimilarPanel docType="lead_post" entityId={1} open onOpenChange={() => {}} />,
    );

    await waitFor(() => expect(screen.getByTestId('similar-error')).toBeInTheDocument());
    expect(screen.getByText('Elasticsearch is down')).toBeInTheDocument();
  });

  it('sends the author filter the user picked', async () => {
    const user = userEvent.setup();
    render(
      <SimilarPanel docType="lead_post" entityId={1} open onOpenChange={() => {}} />,
    );
    await waitFor(() => expect(screen.getByTestId('similar-hit')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Other authors' }));

    await waitFor(() => {
      const last = fetchMock.mock.calls.at(-1);
      expect(JSON.parse(String(last?.[1]?.body)).author).toBe('other');
    });
  });
});

describe('SimilarButton', () => {
  it('opens the panel without navigating its parent link', async () => {
    const user = userEvent.setup();
    render(<SimilarButton docType="lead_post" entityId={1} />);

    expect(screen.queryByTestId('similar-panel')).not.toBeInTheDocument();
    await user.click(screen.getByTestId('similar-button'));

    await waitFor(() => expect(screen.getByTestId('similar-panel')).toBeInTheDocument());
  });
});

describe('RewriteSuggestions', () => {
  it('stays invisible when there is nothing to decide', async () => {
    suggestionItems = [];

    const { container } = render(<RewriteSuggestions externalPostId="test_post_a" />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="rewrite-suggestions"]')).toBeNull();
  });

  it('offers both decisions and nothing else', async () => {
    render(<RewriteSuggestions externalPostId="test_post_a" />);

    await waitFor(() => expect(screen.getByTestId('rewrite-suggestion')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /Same ad/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Not a copy/ })).toBeInTheDocument();
  });

  it('records a rejection and drops the row', async () => {
    const user = userEvent.setup();
    render(<RewriteSuggestions externalPostId="test_post_a" />);
    await waitFor(() => expect(screen.getByTestId('rewrite-suggestion')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /Not a copy/ }));

    await waitFor(() =>
      expect(screen.queryByTestId('rewrite-suggestion')).not.toBeInTheDocument(),
    );
    const decided = fetchMock.mock.calls.filter(([url]) =>
      String(url).endsWith('/reject'),
    );
    expect(decided).toHaveLength(1);
  });
});
