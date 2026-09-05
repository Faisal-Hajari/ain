import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ErrorBoundary } from './ErrorBoundary'

function Boom({ explode }: { explode: boolean }) {
  if (explode) throw new Error('malformed payload')
  return <span>chart</span>
}

describe('ErrorBoundary', () => {
  // React logs the caught error; the noise is expected, not a failure.
  beforeEach(() => vi.spyOn(console, 'error').mockImplementation(() => {}))
  afterEach(() => vi.restoreAllMocks())

  it('renders its children when nothing throws', () => {
    render(
      <ErrorBoundary fallback={() => <span>fallback</span>}>
        <Boom explode={false} />
      </ErrorBoundary>,
    )
    expect(screen.getByText('chart')).toBeInTheDocument()
  })

  it('contains a render-time throw instead of unmounting the tree', () => {
    render(
      <ErrorBoundary fallback={() => <span>fallback</span>}>
        <Boom explode />
      </ErrorBoundary>,
    )
    expect(screen.getByText('fallback')).toBeInTheDocument()
  })

  it('recovers when the reset key changes, so fresh data clears the error', () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="1" fallback={() => <span>fallback</span>}>
        <Boom explode />
      </ErrorBoundary>,
    )
    expect(screen.getByText('fallback')).toBeInTheDocument()

    rerender(
      <ErrorBoundary resetKey="2" fallback={() => <span>fallback</span>}>
        <Boom explode={false} />
      </ErrorBoundary>,
    )
    expect(screen.getByText('chart')).toBeInTheDocument()
  })
})
