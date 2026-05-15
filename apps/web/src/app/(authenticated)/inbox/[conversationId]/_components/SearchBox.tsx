'use client';

import { ChevronDown, ChevronUp, Search, X } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

interface SearchBoxProps {
  value: string;
  onChange: (value: string) => void;
  currentMatch: number;
  totalMatches: number;
  onPrev: () => void;
  onNext: () => void;
}

export function SearchBox({
  value,
  onChange,
  currentMatch,
  totalMatches,
  onPrev,
  onNext,
}: SearchBoxProps) {
  const showCounter = value.length > 0;
  const disabled = totalMatches === 0;

  return (
    <div className="px-4 py-2 flex items-center gap-2">
      <div className="relative flex-1">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          type="text"
          placeholder="Search in conversation..."
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="pl-9 pr-8 h-9"
        />
        {value && (
          <button
            type="button"
            onClick={() => onChange('')}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            aria-label="Clear search"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {showCounter && (
        <div className="flex items-center gap-1 shrink-0">
          <span className="text-xs text-muted-foreground tabular-nums min-w-[5.5rem] text-right">
            {disabled ? '0 of 0' : `${currentMatch} of ${totalMatches}`}
          </span>
          <button
            type="button"
            onClick={onPrev}
            disabled={disabled}
            aria-label="Previous match"
            className={cn(
              'h-7 w-7 rounded inline-flex items-center justify-center',
              'text-muted-foreground hover:text-foreground hover:bg-muted',
              'disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted-foreground'
            )}
          >
            <ChevronUp className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onNext}
            disabled={disabled}
            aria-label="Next match"
            className={cn(
              'h-7 w-7 rounded inline-flex items-center justify-center',
              'text-muted-foreground hover:text-foreground hover:bg-muted',
              'disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted-foreground'
            )}
          >
            <ChevronDown className="h-4 w-4" />
          </button>
        </div>
      )}
    </div>
  );
}
