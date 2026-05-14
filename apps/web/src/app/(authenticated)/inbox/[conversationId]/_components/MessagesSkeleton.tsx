import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

export function MessagesSkeleton() {
  return (
    <div className="space-y-4 p-4">
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} className={cn(
          "flex gap-3",
          i % 2 === 0 ? "flex-row-reverse" : "flex-row"
        )}>
          {i % 2 !== 0 && <Skeleton className="h-8 w-8 rounded-full" />}
          <Skeleton className={cn(
            "h-16 rounded-2xl",
            i % 2 === 0 ? "w-48" : "w-64"
          )} />
        </div>
      ))}
    </div>
  );
}
