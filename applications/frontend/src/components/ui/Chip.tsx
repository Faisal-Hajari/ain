import clsx from 'clsx'
import type { ReactNode } from 'react'
import type { Severity } from '@/api/types'
import { severityChip } from './severity'

export function Chip({
  children,
  severity,
  className,
}: {
  children: ReactNode
  severity?: Severity
  className?: string
}) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1',
        severity ? severityChip[severity] : 'bg-canvas text-muted ring-border',
        className,
      )}
    >
      {children}
    </span>
  )
}

export function LiveDot({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-muted">
      <span className="relative flex size-1.5">
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-ok/70" />
        <span className="relative inline-flex size-1.5 rounded-full bg-ok" />
      </span>
      {label}
    </span>
  )
}
