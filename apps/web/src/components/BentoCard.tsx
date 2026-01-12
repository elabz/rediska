'use client';

import * as React from 'react';
import Link from 'next/link';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

const bentoCardVariants = cva(
  'group relative overflow-hidden transition-all duration-300 hover:shadow-lg',
  {
    variants: {
      variant: {
        default: 'bg-card',
        gradient: 'bg-gradient-to-br from-primary/10 via-primary/5 to-transparent',
        feature: 'bg-gradient-to-br from-primary to-primary/80 text-primary-foreground',
        muted: 'bg-muted/50',
      },
      size: {
        default: 'col-span-1 row-span-1',
        wide: 'col-span-1 md:col-span-2 row-span-1',
        tall: 'col-span-1 row-span-2',
        large: 'col-span-1 md:col-span-2 row-span-2',
        hero: 'col-span-1 md:col-span-2 lg:col-span-3 row-span-1',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
);

export interface BentoCardProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof bentoCardVariants> {
  title?: string;
  description?: string;
  icon?: React.ReactNode;
  href?: string;
  action?: React.ReactNode;
  value?: string | number;
  subtitle?: string;
}

export function BentoCard({
  title,
  description,
  icon,
  href,
  action,
  value,
  subtitle,
  variant,
  size,
  className,
  children,
  ...props
}: BentoCardProps) {
  const cardContent = (
    <div className="flex flex-col h-full">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            {icon && (
              <div
                className={cn(
                  'flex h-10 w-10 items-center justify-center rounded-lg transition-transform group-hover:scale-110',
                  variant === 'feature'
                    ? 'bg-primary-foreground/20 text-primary-foreground'
                    : 'bg-primary/10 text-primary'
                )}
              >
                {icon}
              </div>
            )}
            <div>
              {title && (
                <CardTitle
                  className={cn(
                    'text-base font-semibold',
                    variant === 'feature' && 'text-primary-foreground'
                  )}
                >
                  {title}
                </CardTitle>
              )}
              {subtitle && (
                <p
                  className={cn(
                    'text-xs',
                    variant === 'feature'
                      ? 'text-primary-foreground/70'
                      : 'text-muted-foreground'
                  )}
                >
                  {subtitle}
                </p>
              )}
            </div>
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </div>
        {description && (
          <CardDescription
            className={cn(
              'mt-2',
              variant === 'feature' && 'text-primary-foreground/80'
            )}
          >
            {description}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="flex-1 pb-4">
        {value !== undefined && (
          <div
            className={cn(
              'text-3xl font-bold tracking-tight',
              variant === 'feature' && 'text-primary-foreground'
            )}
          >
            {value}
          </div>
        )}
        {children}
      </CardContent>
    </div>
  );

  const cardClasses = cn(
    bentoCardVariants({ variant, size }),
    href && 'cursor-pointer hover:scale-[1.02] active:scale-[0.98]',
    className
  );

  if (href) {
    return (
      <Card className={cardClasses} {...props}>
        <Link href={href} className="block h-full">
          {cardContent}
        </Link>
      </Card>
    );
  }

  return (
    <Card className={cardClasses} {...props}>
      {cardContent}
    </Card>
  );
}

// Convenience components for common card types
export function StatCard({
  title,
  value,
  change,
  changeType = 'neutral',
  icon,
  ...props
}: {
  title: string;
  value: string | number;
  change?: string;
  changeType?: 'positive' | 'negative' | 'neutral';
  icon?: React.ReactNode;
} & Omit<BentoCardProps, 'title' | 'value'>) {
  return (
    <BentoCard
      title={title}
      icon={icon}
      variant="gradient"
      {...props}
    >
      <div className="mt-2">
        <div className="text-3xl font-bold tracking-tight">{value}</div>
        {change && (
          <p
            className={cn(
              'text-xs mt-1',
              changeType === 'positive' && 'text-success',
              changeType === 'negative' && 'text-destructive',
              changeType === 'neutral' && 'text-muted-foreground'
            )}
          >
            {change}
          </p>
        )}
      </div>
    </BentoCard>
  );
}

export function ActionCard({
  title,
  description,
  icon,
  href,
  ...props
}: {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  href: string;
} & Omit<BentoCardProps, 'title' | 'description' | 'icon' | 'href'>) {
  return (
    <BentoCard
      title={title}
      description={description}
      icon={icon}
      href={href}
      {...props}
    >
      <div className="flex items-center gap-1 text-sm text-primary font-medium mt-2 group-hover:underline">
        <span>Go to {title}</span>
        <svg
          className="w-4 h-4 transition-transform group-hover:translate-x-1"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M9 5l7 7-7 7"
          />
        </svg>
      </div>
    </BentoCard>
  );
}

export default BentoCard;
