'use client';

import { cn } from '@/lib/utils';
import type { Identity } from '@/hooks/useIdentities';

interface IdentityFilterProps {
  identities: Identity[];
  value: number | null;
  onChange: (id: number | null) => void;
  showAll?: boolean;
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

export function IdentityFilter({
  identities,
  value,
  onChange,
  showAll = true,
  className,
}: IdentityFilterProps) {
  return (
    <div className={cn("flex gap-1 p-1 bg-muted rounded-lg overflow-x-auto", className)}>
      {showAll && (
        <button
          onClick={() => onChange(null)}
          className={cn(
            "px-3 py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap",
            value === null
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          All
        </button>
      )}
      {identities.map((identity) => (
        <button
          key={identity.id}
          onClick={() => onChange(identity.id)}
          className={cn(
            "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap",
            value === identity.id
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          <span>{getProviderIcon(identity.provider_id)}</span>
          <span>{identity.display_name}</span>
          {identity.is_default && (
            <span className="text-[10px] opacity-60">(default)</span>
          )}
        </button>
      ))}
    </div>
  );
}

export default IdentityFilter;
