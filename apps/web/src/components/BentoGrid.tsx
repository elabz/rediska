'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

interface BentoGridProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
}

export function BentoGrid({ children, className, ...props }: BentoGridProps) {
  return (
    <div
      className={cn(
        'grid gap-4 auto-rows-[minmax(120px,auto)]',
        'grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4',
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export default BentoGrid;
