import { EmptyState } from '@/components';

export const metadata = {
  title: 'Audit Log - Rediska',
  description: 'System audit log',
};

export default function AuditPage() {
  return (
    <EmptyState
      icon="📋"
      title="Audit Log"
      description="All system actions are recorded here. Filter by action type, identity, or date range to review activity."
    />
  );
}
