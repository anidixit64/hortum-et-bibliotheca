import { bookCover, evenShelf } from './books'
import { placePhotos, sidebarSlots } from './exhibit'
import { themeVariables } from './theme'
import type { WikiImage } from '../api/types'
import { extractProperNouns, linkClues, parseMarks } from './marks'
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

describe('marks', () => {
  it('parses summary marks', () => {
    expect(parseMarks('A [[3|battle royal]] and [[5|Mr. Norton]].')).toEqual([
      { text: 'A ' }, { text: 'battle royal', rank: 3 }, { text: ' and ' },
      { text: 'Mr. Norton', rank: 5 }, { text: '.' },
    ])
  })
  it('links other clues once, longest name first, never itself', () => {
    const clues = [
      { rank: 1, names: ['Ambrose Burnside', 'Burnside'] },
      { rank: 2, names: ["Burnside's Bridge"] },
      { rank: 3, names: ['Antietam'] },
    ]
    const pieces = linkClues("Burnside took Burnside's Bridge at Antietam; Antietam again.", clues, 1)
    expect(pieces.filter((p) => p.rank).map((p) => [p.text, p.rank])).toEqual([
      ["Burnside's Bridge", 2], ['Antietam', 3],
    ])
  })
})

describe('extractProperNouns', () => {
  it('finds capitalized names, including multi-word with joiners', () => {
    const text = 'The Battle of Waterloo was fought near Brussels. Napoleon led the French army.'
    const names = extractProperNouns(text)
    expect(names).toContain('Battle of Waterloo')
    expect(names).toContain('Brussels')
    expect(names).toContain('Napoleon')
    expect(names).toContain('French')
  })
  it('strips marks and finds multi-word names with lowercase joiners', () => {
    const text = '[[1|Some clue]] was used. Alexander the Great conquered Persia.'
    const names = extractProperNouns(text)
    expect(names).toContain('Alexander the Great')
    expect(names).toContain('Persia')
  })
  it('strips leading articles from phrases', () => {
    const names = extractProperNouns('He crossed the Rubicon. The Aztec Empire fell.')
    expect(names).toContain('Rubicon')
    expect(names).toContain('Aztec Empire')
  })
})

describe('themeVariables', () => {
  it('maps light and dark colors and the font pairing to CSS variables', () => {
    const colors = (c: string) => ({ bg: c, surface: c, text: c, muted: c, accent: c, accent2: c, accent_soft: c, header_tint: c })
    const vars = themeVariables({ light: colors('#ffffff'), dark: colors('#000000'), font: 'elegant-serif', header: null })
    expect(vars['--l-accent-soft']).toBe('#ffffff')
    expect(vars['--d-header-tint']).toBe('#000000')
    expect(vars['--font-body']).toContain('Didot')
  })
})

describe('the exhibit shelf', () => {
  const image = (file: string): WikiImage => ({
    file, url: file, width: 100, height: 100, page: null, caption: file,
    artist: null, license: 'CC BY-SA 4.0', license_url: null, attribution_required: false,
    is_main: false,
  })
  it('puts two photos in the summary, three on each side, and the rest in the gallery', () => {
    const images = Array.from({ length: 10 }, (_, i) => image(`File:${i}.jpg`))
    const placed = placePhotos(images, new Set(), false)
    expect(placed.summary.map((item) => item.file)).toEqual(['File:0.jpg', 'File:1.jpg'])
    expect(placed.left).toHaveLength(3)
    expect(placed.right).toHaveLength(3)
    expect(placed.gallery.map((item) => item.file)).toEqual(['File:8.jpg', 'File:9.jpg'])
  })
  it('leads a sidebar with the map or timeline and weaves photos through the other cards', () => {
    expect(sidebarSlots(3, 1, true)).toEqual(['lead', 'photo', 'rest', 'photo', 'photo'])
    expect(sidebarSlots(3, 0, true)).toEqual(['lead', 'photo', 'photo', 'photo'])
    expect(sidebarSlots(0, 1, true)).toEqual(['lead', 'rest'])
  })
  it('keeps an even number of books and builds an ISBN cover', () => {
    const books = Array.from({ length: 9 }, (_, i) => ({
      title: `Book ${i}`, author: null, year: null, isbn: i === 8 ? '9780393000000' : null,
      cover: i === 0 ? 'https://covers.example/a.jpg' : null, open_library: null, cited: 0,
      source: 'cited' as const,
    }))
    expect(evenShelf(books).map((book) => book.title)).toEqual(
      ['Book 0', 'Book 1', 'Book 2', 'Book 3', 'Book 4', 'Book 5', 'Book 6', 'Book 7'],
    )
    expect(evenShelf(books.slice(0, 3))).toHaveLength(2)
    expect(bookCover(books[8])).toBe('https://covers.openlibrary.org/b/isbn/9780393000000-L.jpg')
    expect(bookCover(books[0])).toBe('https://covers.example/a.jpg')
  })
})
