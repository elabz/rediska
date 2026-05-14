'use client';

import { Search, X } from 'lucide-react';
import { Input } from '@/components/ui/input';

interface SearchBoxProps {
  value: string;
  onChange: (value: string) => void;
  filteredCount: number;
  totalCount: number;
}

export function SearchBox({ value, onChange, filteredCount, totalCount }: SearchBoxProps) {
  return (
    <div className="px-4 py-2">
      <div className="relative">
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
            onClick={() => onChange('')}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      {value && (
        <p className="text-xs text-muted-foreground mt-1">
          {filteredCount} of {totalCount} messages match
        </p>
      )}
    </div>
  );
}
