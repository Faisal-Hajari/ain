import clsx from 'clsx'

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('animate-pulse rounded-md bg-border/70', className)} />
}

export function CardSkeleton({ label }: { label: string }) {
  return (
    <div className="flex flex-1 flex-col gap-3" role="status" aria-label={label}>
      <Skeleton className="h-7 w-24" />
      <Skeleton className="h-3 w-40" />
      <Skeleton className="mt-auto h-16 w-full" />
    </div>
  )
}
