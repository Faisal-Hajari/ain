import clsx from 'clsx'
import { useEffect, useRef, type ReactNode } from 'react'

/**
 * Thin wrapper over <dialog>: the browser gives us the focus trap, Escape
 * handling and inert background, so there is no modal logic here.
 */
export function Dialog({
  open,
  title,
  onClose,
  closeLabel,
  size = 'md',
  children,
}: {
  open: boolean
  title: string
  onClose: () => void
  closeLabel: string
  size?: 'md' | 'lg'
  children: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)

  // Syncing an imperative DOM widget with React state: an Effect is correct.
  useEffect(() => {
    const dialog = ref.current
    if (!dialog || !open) return
    dialog.showModal()
    return () => dialog.close()
  }, [open])

  // Separate process, so a new onClose identity rebinds the listener without
  // closing and reopening the modal. The backdrop is the dialog's own box,
  // which React cannot hand us a JSX handler for.
  useEffect(() => {
    const dialog = ref.current
    if (!dialog || !open) return
    const closeOnBackdrop = (event: MouseEvent) => {
      if (event.target === dialog) onClose()
    }
    dialog.addEventListener('click', closeOnBackdrop)
    return () => dialog.removeEventListener('click', closeOnBackdrop)
  }, [open, onClose])

  if (!open) return null

  return (
    <dialog
      ref={ref}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      className={clsx(
        'm-auto rounded-(--radius-card) bg-surface p-0 text-ink backdrop:bg-black/50',
        size === 'lg' ? 'w-[min(72rem,94vw)]' : 'w-[min(46rem,92vw)]',
      )}
    >
      <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-3.5">
        <h2 className="text-sm font-semibold">{title}</h2>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md px-2 py-1 text-xs font-medium text-muted ring-1 ring-border hover:bg-canvas"
        >
          {closeLabel}
        </button>
      </div>
      <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
    </dialog>
  )
}
