import { describe, it, expect } from 'vitest'
import { clampPage, queueColor, quantityText, quantityWithUnit } from '../../app/utils/presentation'

describe('domain status mapping', () => {
  it('maps the four queues to distinct functional colors', () => {
    expect(queueColor('fix')).toBe('error')
    expect(queueColor('review')).toBe('warning')
    expect(queueColor('ok')).toBe('success')
    // A technical failure / unchecked state is neutral, never red.
    expect(queueColor('missing')).toBe('neutral')
    expect(queueColor('unknown')).toBe('neutral')
  })
})

describe('quantity rendering', () => {
  it('keeps precision and separators, never float artifacts', () => {
    expect(quantityText('78.9')).toBe('78,9')
    expect(quantityText(45)).toBe('45')
    expect(quantityText('')).toBe('—')
    expect(quantityText(null)).toBe('—')
    expect(quantityWithUnit('45', 'м')).toBe('45 м')
    expect(quantityWithUnit('45 м', 'м')).toBe('45 м')
    expect(quantityWithUnit(null, null)).toBe('—')
  })
})

describe('physical page clamp', () => {
  it('keeps 1-based PDF.js pages inside the document', () => {
    expect(clampPage(1, 10)).toBe(1)
    expect(clampPage(0, 10)).toBe(1)
    expect(clampPage(-3, 10)).toBe(1)
    expect(clampPage(11, 10)).toBe(10)
    expect(clampPage(Number.NaN, 10)).toBe(1)
  })
})
