import { act, render, renderHook, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, useLocation } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { FilterDef } from '@/api/types'
import { useFilters, useUrlParam, useUrlWriter } from './useFilters'

const wrapper = (entry: string) =>
  function Wrapper({ children }: { children: ReactNode }) {
    return <MemoryRouter initialEntries={[entry]}>{children}</MemoryRouter>
  }

const DEFS: FilterDef[] = [
  { id: 'branch', label: 'Branch', defaultValue: 'olaya', options: [] },
  { id: 'range', label: 'Range', defaultValue: 'today', options: [] },
]

describe('useFilters', () => {
  it('falls back to each filter default when the URL is bare', () => {
    const { result } = renderHook(() => useFilters(DEFS), { wrapper: wrapper('/') })
    expect(result.current.values).toEqual({ branch: 'olaya', range: 'today' })
  })

  it('lets the URL override a default without disturbing the others', () => {
    const { result } = renderHook(() => useFilters(DEFS), { wrapper: wrapper('/?range=30d') })
    expect(result.current.values).toEqual({ branch: 'olaya', range: '30d' })
  })

  it('ignores params that are not declared filters', () => {
    const { result } = renderHook(() => useFilters(DEFS), { wrapper: wrapper('/?expanded=footfall') })
    expect(result.current.values).toEqual({ branch: 'olaya', range: 'today' })
  })
})

describe('useUrlWriter', () => {
  it('applies every key in one patch', () => {
    const { result } = renderHook(
      () => ({ write: useUrlWriter(), search: useLocation().search }),
      { wrapper: wrapper('/?range=today') },
    )

    act(() => result.current.write({ range: '2026-09-02', calendar: null, calendarMonth: null }))

    expect(new URLSearchParams(result.current.search).get('range')).toBe('2026-09-02')
  })

  /**
   * The regression this guards: ElementCard's click-to-zoom listener depends on
   * the writer, so an identity that changed on every render would re-subscribe
   * on every render.
   */
  it('keeps a stable identity across renders at the same URL', () => {
    const { result, rerender } = renderHook(() => useUrlWriter(), { wrapper: wrapper('/?range=today') })
    const first = result.current
    rerender()
    rerender()
    expect(result.current).toBe(first)
  })

  /**
   * It does change when the URL changes, and must: react-router rebuilds
   * setSearchParams per location, so pinning the identity across a navigation
   * would leave the updater resolving against the previous URL. Effects
   * re-subscribe once per navigation, which is the intended cost.
   */
  it('takes a new identity after a navigation', () => {
    const { result } = renderHook(
      () => ({ write: useUrlWriter(), search: useLocation().search }),
      { wrapper: wrapper('/?range=today') },
    )

    const before = result.current.write
    act(() => before({ range: '30d' }))

    expect(result.current.search).toContain('range=30d')
    expect(result.current.write).not.toBe(before)
  })
})

/**
 * The failure this guards against: react-router resolves each setSearchParams
 * against the current location rather than queueing them, so two separate
 * writes in one handler leave only the last one's change.
 */
describe('writing two params from one handler', () => {
  function Probe() {
    const range = useUrlParam('range')
    const calendar = useUrlParam('calendar')
    const write = useUrlWriter()
    const { search } = useLocation()

    return (
      <>
        <output>{search}</output>
        <button type="button" onClick={() => write({ range: '2026-09-02', calendar: null })}>
          batched
        </button>
        <button
          type="button"
          onClick={() => {
            range.set('2026-09-02')
            calendar.set(null)
          }}
        >
          separate
        </button>
      </>
    )
  }

  it('keeps both changes when batched through one writer call', () => {
    render(<Probe />, { wrapper: wrapper('/?calendar=open') })
    act(() => screen.getByText('batched').click())

    const params = new URLSearchParams(screen.getByRole('status').textContent ?? '')
    expect(params.get('range')).toBe('2026-09-02')
    expect(params.get('calendar')).toBeNull()
  })

  it('loses the first change when written separately', () => {
    render(<Probe />, { wrapper: wrapper('/?calendar=open') })
    act(() => screen.getByText('separate').click())

    const params = new URLSearchParams(screen.getByRole('status').textContent ?? '')
    expect(params.get('calendar')).toBeNull()
    expect(params.get('range')).toBeNull()
  })
})
