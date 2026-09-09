import { cn } from '@/lib/utils';

function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('shimmer rounded-md bg-white/[0.05]', className)}
      aria-hidden
      {...props}
    />
  );
}

export { Skeleton };
