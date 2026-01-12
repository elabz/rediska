'use client';

import { Check, ChevronDown, User } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import type { Identity } from '@/hooks/useIdentities';

interface IdentitySelectorProps {
  identities: Identity[];
  selected: number | null;
  onChange: (id: number) => void;
  className?: string;
  disabled?: boolean;
}

function getProviderIcon(providerId: string): string {
  switch (providerId) {
    case 'reddit':
      return '🔸';
    default:
      return '🔹';
  }
}

export function IdentitySelector({
  identities,
  selected,
  onChange,
  className,
  disabled = false,
}: IdentitySelectorProps) {
  const selectedIdentity = identities.find(i => i.id === selected);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          className={cn("justify-between", className)}
          disabled={disabled || identities.length === 0}
        >
          <span className="flex items-center gap-2 truncate">
            {selectedIdentity ? (
              <>
                <span>{getProviderIcon(selectedIdentity.provider_id)}</span>
                <span className="truncate">{selectedIdentity.display_name}</span>
              </>
            ) : (
              <>
                <User className="h-4 w-4" />
                <span>Select identity</span>
              </>
            )}
          </span>
          <ChevronDown className="h-4 w-4 ml-2 shrink-0 opacity-50" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-[200px]">
        {identities.map((identity) => (
          <DropdownMenuItem
            key={identity.id}
            onClick={() => onChange(identity.id)}
            className="cursor-pointer"
          >
            <span className="mr-2">{getProviderIcon(identity.provider_id)}</span>
            <span className="flex-1 truncate">{identity.display_name}</span>
            {identity.id === selected && (
              <Check className="h-4 w-4 ml-2 shrink-0" />
            )}
            {identity.is_default && identity.id !== selected && (
              <span className="text-xs text-muted-foreground ml-2">(default)</span>
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export default IdentitySelector;
