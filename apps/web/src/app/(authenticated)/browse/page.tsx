import { EmptyState } from '@/components';

export const metadata = {
  title: 'Browse - Rediska',
  description: 'Browse provider locations',
};

export default function BrowsePage() {
  return (
    <EmptyState
      icon="🔍"
      title="Browse locations"
      description="Select a provider and location to browse posts. You can save interesting posts as leads for follow-up."
    />
  );
}
