import { EmptyState } from '@/components';

export const metadata = {
  title: 'Search - Rediska',
  description: 'Search across all content',
};

export default function SearchPage() {
  return (
    <EmptyState
      icon="🔎"
      title="Search your data"
      description="Search across conversations, leads, and profiles. Enter a query above to find what you're looking for."
    />
  );
}
