import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import { SearchBox } from '../components/SearchBox'
import { PracticePage } from '../pages/PracticePage'
import { ReviewPage } from '../pages/ReviewPage'

type Handler = (url: string, init?: RequestInit) => unknown

function mockFetch(handler: Handler) {
  const calls: { url: string; init?: RequestInit }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    const body = handler(url, init)
    return new Response(body === undefined ? null : JSON.stringify(body), {
      status: body === undefined ? 404 : 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }))
  return calls
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

test('search shows results that link to the topic page', async () => {
  mockFetch((url) =>
    url.startsWith('/api/catalog/search')
      ? [{ id: 'Q2736', name: 'Association football', category: 'Pop Culture', description: 'team sport',
           n_tossups: 10, matched_alias: 'soccer', score: 1 }]
      : undefined,
  )
  render(<MemoryRouter><SearchBox /></MemoryRouter>)
  await userEvent.type(screen.getByLabelText('Search topics'), 'socer')
  const link = await screen.findByRole('link', { name: /Association football/ })
  expect(link).toHaveAttribute('href', '/topic/Q2736')
  expect(link).toHaveTextContent('“soccer”')
})

test('review flips a card, rates it and moves on', async () => {
  const calls = mockFetch((url) =>
    url.startsWith('/api/study/reviews/due')
      ? [
          { card_id: 'a', topic_id: 'Q1', kind: 'clue', front: 'Ras leads a riot.', back: 'Invisible Man', due: '' },
          { card_id: 'b', topic_id: 'Q1', kind: 'reverse', front: 'Name 3 clues', back: 'Ras', due: '' },
        ]
      : url === '/api/study/reviews' ? { due: '2026-10-11' } : undefined,
  )
  render(<MemoryRouter><ReviewPage /></MemoryRouter>)
  expect(await screen.findByText('Ras leads a riot.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Show answer' }))
  expect(screen.getByText('Invisible Man')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Good' }))
  expect(await screen.findByText('Name 3 clues')).toBeInTheDocument()
  const review = calls.find((c) => c.url === '/api/study/reviews')
  expect(JSON.parse(String(review?.init?.body))).toEqual({ card_id: 'a', rating: 3 })
})

test('practice reveals words, buzzes on space, judges and offers an override', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const calls = mockFetch((url, init) => {
    if (url.startsWith('/api/catalog/practice/next'))
      return { id: 'q1', set_name: 'ACF', year: 2024, difficulty: 7, category: 'Literature', subcategory: null,
               question: 'He is expelled by Bledsoe. For 10 points, name this novel.', power_word: 2,
               answer: 'Invisible Man', answer_html: null, topic_id: 'Q1784288', clues: [] }
    if (url === '/api/study/buzzes')
      return { buzz_id: 7, result: 'incorrect', recorded: true, judged_by: 'auto', position: 0.2,
               clue_ordinal: 0, in_power: true, answer: 'Invisible Man', missed_cards: 1,
               _echo: JSON.parse(String(init?.body)) }
    if (url === '/api/study/buzzes/7') return { result: 'correct' }
    return undefined
  })
  render(<MemoryRouter initialEntries={['/practice?topic=Q1784288']}><PracticePage /></MemoryRouter>)
  await screen.findByRole('button', { name: /Buzz/ })
  for (let i = 0; i < 4; i++) await act(async () => { vi.advanceTimersByTime(300) }) // 200 wpm
  expect(screen.getByText(/expelled/)).toBeInTheDocument()
  fireEvent.keyDown(window, { code: 'Space' })
  await userEvent.type(await screen.findByLabelText('Your answer'), 'Invisble Man{enter}')
  expect(await screen.findByText('Incorrect')).toBeInTheDocument()
  const buzz = calls.find((c) => c.url === '/api/study/buzzes')
  expect(JSON.parse(String(buzz?.init?.body))).toMatchObject({ tossup_id: 'q1', answer_given: 'Invisble Man' })
  await userEvent.click(screen.getByRole('button', { name: 'I was right' }))
  expect(await screen.findByText('Correct')).toBeInTheDocument()
  expect(calls.find((c) => c.url === '/api/study/buzzes/7')?.init?.method).toBe('PATCH')
})
