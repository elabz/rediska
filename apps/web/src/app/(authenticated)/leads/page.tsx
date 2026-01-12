import { EmptyState } from '@/components';

export const metadata = {
  title: 'Leads - Rediska',
  description: 'Saved leads and prospects',
};

export default function LeadsPage() {
  return (
    <EmptyState
      icon="🎯"
      title="No leads saved"
      description="Browse locations to find and save potential leads. Saved leads will appear here for analysis and outreach."
    />
  );
}
