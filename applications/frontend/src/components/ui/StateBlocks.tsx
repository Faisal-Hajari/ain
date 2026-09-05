import type { ReactNode } from 'react'

export function ErrorState({ message, onRetry, retryLabel }: { message: string; onRetry?: () => void; retryLabel: string }) {
  return (
    <div className="flex flex-1 flex-col items-start justify-center gap-2 text-sm">
      <p className="text-critical">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md px-2 py-1 text-xs font-medium text-brand ring-1 ring-border hover:bg-canvas"
        >
          {retryLabel}
        </button>
      ) : null}
    </div>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-(--radius-card) border border-dashed border-border px-5 py-10 text-center text-sm text-muted">
      {children}
    </div>
  )
}
