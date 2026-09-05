import clsx from 'clsx'
import type { HTMLAttributes, ReactNode, Ref } from 'react'

/** The one card shell every element on the dashboard is built from. */
export function Card({
  className,
  interactive = false,
  ref,
  children,
  ...rest
}: {
  className?: string
  interactive?: boolean
  ref?: Ref<HTMLElement>
  children: ReactNode
} & HTMLAttributes<HTMLElement>) {
  return (
    <section
      ref={ref}
      className={clsx(
        'flex h-full flex-col rounded-(--radius-card) bg-surface ring-1 ring-border',
        'shadow-[0_1px_2px_rgba(16,24,40,0.06)] transition',
        interactive && 'hover:ring-brand/40 hover:shadow-[0_6px_20px_rgba(16,24,40,0.10)]',
        className,
      )}
      {...rest}
    >
      {children}
    </section>
  )
}

export function CardHeader({
  title,
  description,
  actions,
  titleId,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  titleId?: string
}) {
  return (
    <header className="flex items-start justify-between gap-3 px-5 pt-4">
      <div className="min-w-0">
        <h3 id={titleId} className="truncate text-sm font-semibold text-ink">
          {title}
        </h3>
        {description ? <p className="mt-0.5 line-clamp-2 text-xs text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-1.5">{actions}</div> : null}
    </header>
  )
}

export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx('flex min-h-0 flex-1 flex-col px-5 py-4', className)}>{children}</div>
}

export function CardFooter({ children }: { children: ReactNode }) {
  return (
    <footer className="flex flex-wrap items-center gap-2 border-t border-border px-5 py-2.5 text-[11px] text-muted">
      {children}
    </footer>
  )
}
