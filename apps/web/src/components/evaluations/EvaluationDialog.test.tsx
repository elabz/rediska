import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EvaluationDialog } from './EvaluationDialog';
import { EvaluationBadge } from './EvaluationBadge';
import { validateEvaluation, parseList } from '@/lib/evaluations';

describe('validateEvaluation', () => {
  it('requires missing_info when missing_context is tagged', () => {
    expect(
      validateEvaluation({ reason_tags: ['missing_context'], missing_info: '', dimension: null, corrected_value: null })
    ).toMatch(/what information/i);
    expect(
      validateEvaluation({ reason_tags: ['missing_context'], missing_info: 'home state', dimension: null, corrected_value: null })
    ).toBeNull();
  });

  it('rejects an unknown corrected recommendation for the final verdict', () => {
    expect(
      validateEvaluation({ reason_tags: [], missing_info: null, dimension: null, corrected_value: { recommendation: 'maybe' } })
    ).toMatch(/must be/i);
    expect(
      validateEvaluation({ reason_tags: [], missing_info: null, dimension: null, corrected_value: { recommendation: 'suitable' } })
    ).toBeNull();
  });

  it('parses comma or newline separated lists', () => {
    expect(parseList('a, b;c\n d ,')).toEqual(['a', 'b', 'c', 'd']);
  });
});

describe('EvaluationBadge', () => {
  it('renders nothing when unevaluated and showEmpty is false', () => {
    const { container } = render(<EvaluationBadge evaluation={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders "Not evaluated" when showEmpty', () => {
    render(<EvaluationBadge evaluation={null} showEmpty />);
    expect(screen.getByText(/not evaluated/i)).toBeInTheDocument();
  });

  it('renders the verdict and tags', () => {
    render(
      <EvaluationBadge
        evaluation={{
          id: 1,
          human_verdict: 'disagree',
          reason_tags: ['wrong_age', 'too_strict'],
          corrected_value: null,
          missing_info: null,
          notes: null,
          created_at: '2026-09-16T00:00:00Z',
        }}
      />
    );
    expect(screen.getByTestId('evaluation-badge')).toHaveTextContent('Disagree');
    expect(screen.getByText('Wrong age')).toBeInTheDocument();
    expect(screen.getByText('Too strict')).toBeInTheDocument();
  });
});

describe('EvaluationDialog', () => {
  beforeEach(() => {
    vi.mocked(global.fetch).mockClear();
  });

  it('blocks save when missing_context is tagged without missing_info', async () => {
    const user = userEvent.setup();
    render(
      <EvaluationDialog
        open
        onOpenChange={() => {}}
        subjectType="lead_analysis"
        subjectId={1}
        dimension="demographics"
        agentOutput={{ age: 30 }}
      />
    );

    await user.click(screen.getByRole('radio', { name: /disagree/i }));
    await user.click(screen.getByRole('button', { name: /missing context/i }));
    await user.click(screen.getByRole('button', { name: /save evaluation/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/what information/i);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('posts the payload with a corrected value and reports the saved evaluation', async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    const onOpenChange = vi.fn();
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      status: 201,
      json: async () => ({
        id: 42,
        human_verdict: 'disagree',
        reason_tags: ['wrong_age'],
        corrected_value: { age: 41 },
        missing_info: null,
        notes: null,
        created_at: '2026-09-16T00:00:00Z',
      }),
    } as Response);

    render(
      <EvaluationDialog
        open
        onOpenChange={onOpenChange}
        subjectType="lead_analysis"
        subjectId={7}
        dimension="demographics"
        agentOutput={{ age: 30 }}
        onSaved={onSaved}
      />
    );

    await user.click(screen.getByRole('radio', { name: /disagree/i }));
    await user.click(screen.getByRole('button', { name: /wrong age/i }));
    await user.type(screen.getByLabelText(/^age$/i), '41');
    await user.click(screen.getByRole('button', { name: /save evaluation/i }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const [url, init] = vi.mocked(global.fetch).mock.calls[0];
    expect(url).toBe('/api/core/evaluations');
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toMatchObject({
      subject_type: 'lead_analysis',
      subject_id: 7,
      dimension: 'demographics',
      human_verdict: 'disagree',
      reason_tags: ['wrong_age'],
      corrected_value: { age: 41 },
    });
    expect(onSaved.mock.calls[0][0]).toMatchObject({ id: 42, human_verdict: 'disagree' });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('shows the backend error on a failed save', async () => {
    const user = userEvent.setup();
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: async () => ({ detail: 'Analysis not found: 9' }),
    } as Response);

    render(
      <EvaluationDialog open onOpenChange={() => {}} subjectType="lead_analysis" subjectId={9} dimension={null} agentRecommendation="suitable" />
    );
    await user.click(screen.getByRole('button', { name: /save evaluation/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Analysis not found: 9');
  });
});

describe('AgentInputSections', () => {
  it('parses and merges sections across agents, noting who received each', async () => {
    const { AgentInputSections, mergeSections } = await import('./AgentInputSections');
    const inputs = {
      demographics: {
        source: 'stored',
        prompt: 'Analyze:\n\n<title>T</title>\n\n<body>B</body>\n\n<profile_summary>P</profile_summary>',
        sections: ['title', 'body', 'profile_summary'], total_chars: 60, attempt: 1,
      },
      preferences: {
        source: 'stored',
        prompt: '<title>T</title>\n\n<body>B</body>\n\n<interests_summary>I</interests_summary>\n\n<recent_posts>one\n---\ntwo</recent_posts>',
        sections: ['title', 'body', 'interests_summary', 'recent_posts'], total_chars: 90, attempt: 1,
      },
    };
    const merged = mergeSections(inputs);
    expect(merged.map((s) => s.name)).toEqual(['title', 'body', 'profile_summary', 'interests_summary', 'recent_posts']);
    expect(merged.find((s) => s.name === 'body')?.dims).toEqual(['demographics', 'preferences']);
    expect(merged.find((s) => s.name === 'profile_summary')?.dims).toEqual(['demographics']);

    render(<AgentInputSections inputs={inputs} defaultOpen />);
    expect(screen.getByText('Post body')).toBeInTheDocument();
    expect(screen.getByText('Interests summary')).toBeInTheDocument();
    expect(screen.getByText('two')).toBeInTheDocument();
    expect(screen.getByText(/not sent to Preferences/)).toBeInTheDocument();
  });
});


describe('EvaluationControl', () => {
  beforeEach(() => {
    vi.mocked(global.fetch).mockClear();
  });

  it('Agree saves in one click without opening the form', async () => {
    const { EvaluationControl } = await import('./EvaluationControl');
    const user = userEvent.setup();
    const onSaved = vi.fn();
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      status: 201,
      json: async () => ({ id: 5, human_verdict: 'agree', reason_tags: [], created_at: '2026-09-16T00:00:00Z' }),
    } as Response);

    render(
      <EvaluationControl subjectType="lead_analysis" subjectId={3} dimension={null} evaluation={null} onSaved={onSaved} />
    );
    await user.click(screen.getByRole('button', { name: /^agree with final verdict/i }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const body = JSON.parse((vi.mocked(global.fetch).mock.calls[0][1] as RequestInit).body as string);
    expect(body).toMatchObject({ subject_id: 3, dimension: null, human_verdict: 'agree', reason_tags: [] });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByTestId('evaluation-badge')).toHaveTextContent('Agree');
  });

  it('Disagree opens the form pre-set to Disagree', async () => {
    const { EvaluationControl } = await import('./EvaluationControl');
    const user = userEvent.setup();
    render(
      <EvaluationControl subjectType="lead_analysis" subjectId={3} dimension="demographics" evaluation={null} />
    );
    await user.click(screen.getByRole('button', { name: /disagree with demographics/i }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /disagree/i })).toHaveAttribute('aria-checked', 'true');
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
