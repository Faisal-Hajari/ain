import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { HeatmapPayload } from '@/api/types'
import { HeatmapView } from './HeatmapView'

const base: Omit<HeatmapPayload, 'cells'> = { xLabels: ['08', '09'], yLabels: ['Mon', 'Tue'], unit: 'people' }

const opacities = (container: HTMLElement) =>
  [...container.querySelectorAll<HTMLElement>('[title]')].map((cell) => Number(cell.style.opacity))

describe('HeatmapView', () => {
  it('scales opacity against the busiest cell', () => {
    const { container } = render(<HeatmapView data={{ ...base, cells: [[0, 50], [25, 100]] }} />)
    const [quietest, , , busiest] = opacities(container)
    expect(busiest).toBeCloseTo(1)
    expect(quietest).toBeLessThan(busiest as number)
  })

  // An all-zero period divided by a zero max, and NaN opacity is dropped by the
  // browser - so "no incidents" painted identically to peak activity.
  it('keeps an all-zero matrix faint rather than saturated', () => {
    const { container } = render(<HeatmapView data={{ ...base, cells: [[0, 0], [0, 0]] }} />)
    for (const opacity of opacities(container)) {
      expect(Number.isFinite(opacity)).toBe(true)
      expect(opacity).toBeLessThan(0.2)
    }
  })

  it('renders a missing reading as an empty cell', () => {
    const { container } = render(<HeatmapView data={{ ...base, cells: [[null, 10], [5, 10]] }} />)
    expect(opacities(container)[0]).toBeCloseTo(0.3)
  })
})
