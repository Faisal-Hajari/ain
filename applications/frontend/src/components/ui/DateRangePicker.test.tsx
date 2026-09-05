import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { FilterOption } from '@/api/types'
import { DateRangePicker } from './DateRangePicker'

const OPTIONS: FilterOption[] = [
  { value: 'today', label: 'Today' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
]

const LABELS = { from: 'From', previousMonth: 'Previous month', nextMonth: 'Next month', chooseStartDate: 'Or pick a start date' }

function setup(value: string, entry = '/') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <DateRangePicker
        paramKey="range"
        label="Date range"
        value={value}
        options={OPTIONS}
        today="2026-09-05"
        locale="en"
        labels={LABELS}
      />
    </MemoryRouter>,
  )
}

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

  it('ignores a malformed calendarMonth and opens on today instead', () => {
    expect(() => setup('today', '/?calendar=open&calendarMonth=zzz')).not.toThrow()
    expect(screen.getByText('September 2026')).toBeTruthy()
  })

  it('ignores an out-of-range month number', () => {
    expect(() => setup('today', '/?calendar=open&calendarMonth=2026-13')).not.toThrow()
    expect(screen.getByText('September 2026')).toBeTruthy()
  })

  it('disables days after today', () => {
    setup('today', '/?calendar=open')
    expect(screen.getByRole('button', { name: '4' })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: '6' })).toBeDisabled()
  })
})
