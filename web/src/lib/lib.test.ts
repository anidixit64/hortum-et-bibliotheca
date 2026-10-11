import { applyCleanup } from './cleanClues'
import type { Clue } from '../api/types'
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

describe('applyCleanup', () => {
  const record = (id: number, label: string, hist: number[], text = `${label} text`): Clue => ({
    rank: id, cluster_id: id, label, text, examples: [], n_sets: 2, n_tossups: 2,
    median_position: 0.5,
    heatmap: { position_hist: hist, share_in_power: 0, share_last_line: 0, difficulty: {},
               years: [2000, 2020], trend: 'steady' },
  })
  it('builds merged clues from their records and drops unknown ones', () => {
    const records = [record(1, 'lodgers', [1, 0]), record(2, 'boarders', [0, 2]), record(3, 'furs', [1, 1])]
    const out = applyCleanup(records, [
      { rank: 1, label: 'lodgers', n_questions: 5, clue_ids: [1, 2], spellings: ['lodgers', 'boarders'] },
      { rank: 2, label: 'picture of a woman in furs', n_questions: 2, clue_ids: [3], spellings: ['furs'] },
      { rank: 3, label: 'missing', n_questions: 1, clue_ids: [99], spellings: [] },
    ])
    expect(out.map((c) => [c.label, c.n_questions, c.rank])).toEqual([
      ['lodgers', 5, 1],
      ['picture of a woman in furs', 2, 2],
    ])
    expect(out[0].heatmap.position_hist).toEqual([1, 2])
    expect(out[0].examples).toEqual(['boarders text'])
  })
})
