import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EmptyState } from './EmptyState';

describe('EmptyState', () => {
  describe('rendering', () => {
    it('renders title', () => {
      render(
        <EmptyState
          title="No items"
          description="There are no items to display."
        />
      );

      expect(screen.getByRole('heading', { name: /no items/i })).toBeInTheDocument();
    });

    it('renders description', () => {
      render(
        <EmptyState
          title="No items"
          description="There are no items to display."
        />
      );

      expect(screen.getByText(/there are no items to display/i)).toBeInTheDocument();
    });

    it('renders default icon when not provided', () => {
      render(
        <EmptyState
          title="Empty"
          description="Nothing here."
        />
      );

      expect(screen.getByText('📭')).toBeInTheDocument();
    });

    it('renders custom icon when provided', () => {
      render(
        <EmptyState
          title="Empty"
          description="Nothing here."
          icon="🎉"
        />
      );

      expect(screen.getByText('🎉')).toBeInTheDocument();
    });
  });

  describe('accessibility', () => {
    it('icon has aria-hidden attribute', () => {
      render(
        <EmptyState
          title="Empty"
          description="Nothing here."
          icon="📦"
        />
      );

      const icon = screen.getByText('📦');
      expect(icon).toHaveAttribute('aria-hidden', 'true');
    });

    it('title is a heading element', () => {
      render(
        <EmptyState
          title="Empty State Title"
          description="Description text"
        />
      );

      expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Empty State Title');
    });
  });
});
