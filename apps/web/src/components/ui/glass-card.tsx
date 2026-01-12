import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const glassCardVariants = cva(
  'rounded-xl border backdrop-blur-md transition-all duration-300',
  {
    variants: {
      variant: {
        default: [
          'bg-white/70 dark:bg-slate-900/70',
          'border-white/20 dark:border-white/10',
          'shadow-[0_8px_32px_rgba(0,0,0,0.08)]',
          'dark:shadow-[0_8px_32px_rgba(0,0,0,0.3)]',
        ],
        frosted: [
          'bg-white/50 dark:bg-slate-900/50',
          'border-white/30 dark:border-white/10',
          'shadow-[0_8px_32px_rgba(0,0,0,0.06)]',
          'dark:shadow-[0_8px_32px_rgba(0,0,0,0.25)]',
        ],
        subtle: [
          'bg-white/30 dark:bg-slate-900/30',
          'border-white/10 dark:border-white/5',
          'shadow-sm',
        ],
        colorful: [
          'bg-gradient-to-br from-primary/10 via-white/60 to-secondary/10',
          'dark:from-primary/20 dark:via-slate-900/60 dark:to-secondary/20',
          'border-white/20 dark:border-white/10',
          'shadow-[0_8px_32px_rgba(0,0,0,0.1)]',
        ],
      },
      hover: {
        none: '',
        lift: 'hover:shadow-lg hover:-translate-y-0.5',
        glow: 'hover:shadow-[0_0_30px_rgba(59,130,246,0.2)]',
        scale: 'hover:scale-[1.02]',
      },
    },
    defaultVariants: {
      variant: 'default',
      hover: 'lift',
    },
  }
);

export interface GlassCardProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof glassCardVariants> {}

const GlassCard = React.forwardRef<HTMLDivElement, GlassCardProps>(
  ({ className, variant, hover, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(glassCardVariants({ variant, hover }), className)}
      {...props}
    />
  )
);
GlassCard.displayName = 'GlassCard';

// Glass container for modals and overlays
const GlassOverlay = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      'fixed inset-0 z-50 bg-black/60 backdrop-blur-sm',
      'data-[state=open]:animate-in data-[state=closed]:animate-out',
      'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
      className
    )}
    {...props}
  />
));
GlassOverlay.displayName = 'GlassOverlay';

// Glass panel for sidebars and drawers
const GlassPanel = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      'bg-white/80 dark:bg-slate-900/80',
      'backdrop-blur-xl',
      'border border-white/20 dark:border-white/10',
      className
    )}
    {...props}
  />
));
GlassPanel.displayName = 'GlassPanel';

export { GlassCard, GlassOverlay, GlassPanel, glassCardVariants };
