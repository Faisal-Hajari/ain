import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { FilterOption } from '@/api/types'
import { DateRangePicker } from './DateRangePicker'

const OPTIONS: FilterOption[] = [
  { value: 'today', label: 'Today' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
]

const LABELS = { from: 'From', chooseStartDate: 'Or pick a start date' }

/** Surfaces the URL the control writes, since the write is the whole behaviour. */
function Search() {
  return <output data-testid="search">{useLocation().search}</output>
}

function setup(value: string, entry = '/', today = '2026-09-05') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <DateRangePicker
        paramKey="range"
        label="Date range"
        value={value}
        options={OPTIONS}
        today={today}
        locale="en"
        labels={LABELS}
      />
      <Search />
    </MemoryRouter>,
  )
}

const search = () => screen.getByTestId('search').textContent
const dateInput = () => screen.getByLabelText('Or pick a start date') as HTMLInputElement

/**
 * The range and calendar params are read straight off the URL, which anyone can
 * edit or truncate. Intl.DateTimeFormat.format throws RangeError on an invalid
 * Date rather than returning a placeholder, so these used to white-screen the app.
 */
describe('DateRangePicker with untrusted URL input', () => {
  it('shows a preset label as-is', () => {
    setup('7d')
    expect(screen.getByRole('button', { name: /date range/i })).toHaveTextContent('Last 7 days')
  })

  it('formats a valid ISO start date', () => {
    setup('2026-09-02')
    expect(screen.getByRole('button', { name: /date range/i })).toHaveTextContent('From Sep 2, 2026')
  })

  it('falls back instead of throwing on a value that is neither', () => {
    expect(() => setup('xyz')).not.toThrow()
    expect(screen.getByRole('button', { name: /date range/i })).toHaveTextContent('Today')
  })

  it('rejects a well-shaped but impossible date', () => {
    expect(() => setup('2026-02-31')).not.toThrow()
    expect(screen.getByRole('button', { name: /date range/i })).toHaveTextContent('Today')
  })

  it('leaves the date input empty for a preset value', () => {
    setup('7d', '/?calendar=open')
    expect(dateInput().value).toBe('')
  })

  it('does not feed an unparseable value to the date input', () => {
    expect(() => setup('2026-02-31', '/?calendar=open')).not.toThrow()
    expect(dateInput().value).toBe('')
  })

  it('pre-fills the date input with a valid ISO value', () => {
    setup('2026-09-02', '/?calendar=open')
    expect(dateInput().value).toBe('2026-09-02')
  })

  /**
   * `today` is backend JSON, and it bounds the input's `max`. FilterBar sits
   * above every card-level boundary, so a throw here takes the page down rather
   * than one card.
   */
  it('withholds the date input rather than throwing on a malformed today', () => {
    expect(() => setup('today', '/?calendar=open', '05/09/2026')).not.toThrow()
    expect(screen.queryByLabelText('Or pick a start date')).toBeNull()
    // The presets still work without a trustworthy today.
    expect(screen.getByRole('button', { name: 'Last 7 days' })).toBeInTheDocument()
  })

  it('withholds the date input when today is a real-looking but impossible date', () => {
    expect(() => setup('today', '/?calendar=open', '2026-02-31')).not.toThrow()
    expect(screen.queryByLabelText('Or pick a start date')).toBeNull()
  })

  it('shows the date input when today is valid', () => {
    setup('today', '/?calendar=open')
    expect(dateInput()).toBeInTheDocument()
  })

  /** jsdom does not enforce `max`, so assert the bound the browser enforces. */
  it('bounds the input at today so future days cannot be picked', () => {
    setup('today', '/?calendar=open')
    expect(dateInput()).toHaveAttribute('max', '2026-09-05')
  })

  it('writes the picked day and closes the panel in one go', () => {
    setup('today', '/?calendar=open')
    fireEvent.change(dateInput(), { target: { value: '2026-09-02' } })
    expect(new URLSearchParams(search() ?? '').get('range')).toBe('2026-09-02')
    expect(search()).not.toContain('calendar')
    expect(screen.queryByLabelText('Or pick a start date')).toBeNull()
  })

  it('ignores a cleared date input', () => {
    setup('2026-09-02', '/?calendar=open')
    fireEvent.change(dateInput(), { target: { value: '' } })
    expect(search()).toContain('calendar=open')
  })

  it('writes a preset and closes the panel', () => {
    setup('today', '/?calendar=open')
    fireEvent.click(screen.getByRole('button', { name: 'Last 7 days' }))
    expect(new URLSearchParams(search() ?? '').get('range')).toBe('7d')
    expect(search()).not.toContain('calendar')
  })
})
