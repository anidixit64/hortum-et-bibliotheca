import { binOf, cellShades } from './heatmap'
import { formatTime, percent, yearOf } from './format'
import { clueAt, msPerWord, pastPower, words } from './reveal'

const spans = [
  { ordinal: 0, kind: 'clue' as const, word_start: 0, word_end: 4, in_power: true, cluster_id: 1 },
  { ordinal: 1, kind: 'giveaway' as const, word_start: 4, word_end: 9, in_power: false, cluster_id: null },
]

test('reveal helpers', () => {
  expect(words(' He was  expelled. ')).toEqual(['He', 'was', 'expelled.'])
  expect(msPerWord(200)).toBe(300)
  expect(clueAt(spans, 3)?.ordinal).toBe(0)
  expect(clueAt(spans, 4)?.kind).toBe('giveaway')
  expect(clueAt(spans, 99)).toBeUndefined()
  expect(pastPower(5, 4)).toBe(false)
  expect(pastPower(5, 5)).toBe(true)
  expect(pastPower(null, 50)).toBe(false)
})

test('heatmap shades scale to the busiest cell and leave empty cells blank', () => {
  const shades = cellShades([[0, 2], [4, 1]])
  expect(shades[0][0]).toBe(0)
  expect(shades[1][0]).toBe(1)
  expect(shades[0][1]).toBeCloseTo(0.575)
  expect(binOf(0)).toBe(0)
  expect(binOf(0.999)).toBe(9)
  expect(binOf(1)).toBe(9)
})

test('formatting', () => {
  expect(percent(0.5)).toBe('50%')
  expect(percent(null)).toBe('—')
  expect(formatTime('1952-04-14T00:00:00Z', 11)).toBe('14 Apr 1952')
  expect(formatTime('1952-01-01T00:00:00Z', 9)).toBe('1952')
  expect(formatTime('-0490-01-01T00:00:00Z', 9)).toBe('490 BC')
  expect(yearOf('-0490-01-01T00:00:00Z')).toBe(-490)
  expect(yearOf(null)).toBeNull()
})
