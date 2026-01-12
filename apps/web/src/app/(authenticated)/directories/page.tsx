import { EmptyState } from '@/components';

export const metadata = {
  title: 'Directories - Rediska',
  description: 'Contact directories',
};

export default function DirectoriesPage() {
  return (
    <EmptyState
      icon="📁"
      title="No contacts yet"
      description="Directories show your analyzed, contacted, and engaged contacts. Start by analyzing leads to build your directories."
    />
  );
}
