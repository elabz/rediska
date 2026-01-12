'use client';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { Identity } from '@/hooks/useIdentities';

interface IdentityBadgeProps {
  identity: Identity | { provider_id: string; display_name: string; external_username: string };
  variant?: 'default' | 'outline' | 'secondary';
  size?: 'sm' | 'md';
  showUsername?: boolean;
  className?: string;
}

function getProviderIcon(providerId: string): string {
  switch (providerId) {
    case 'reddit':
      return '🔸';
    default:
      return '🔹';
  }
}

function getProviderColor(providerId: string): string {
  switch (providerId) {
    case 'reddit':
      return 'bg-orange-500/10 text-orange-600 border-orange-500/20';
    default:
      return 'bg-blue-500/10 text-blue-600 border-blue-500/20';
  }
}

export function IdentityBadge({
  identity,
  variant = 'outline',
  size = 'sm',
  showUsername = false,
  className,
}: IdentityBadgeProps) {
  const icon = getProviderIcon(identity.provider_id);
  const colorClass = variant === 'outline' ? getProviderColor(identity.provider_id) : '';

  return (
    <Badge
      variant={variant}
      className={cn(
        size === 'sm' ? 'text-xs h-5 px-1.5' : 'text-sm h-6 px-2',
        colorClass,
        className
      )}
    >
      <span className="mr-1">{icon}</span>
      {identity.display_name}
      {showUsername && identity.external_username !== identity.display_name && (
        <span className="ml-1 opacity-70">({identity.external_username})</span>
      )}
    </Badge>
  );
}

export default IdentityBadge;
