import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { vi } from 'vitest'
import { TopicPage } from '../pages/TopicPage'
import record from './fixtures/invisible-man.json'

// A real record from the pipeline (Invisible Man, October 2026): the contract between
// the snapshot stage and the topic page.
test('the topic page renders a real record', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const body = url.startsWith('/api/catalog/topics/')
      ? record
      : url.startsWith('/api/content/')
        ? content('ready')
        : { topic_id: 'Q1784288', followed: false, cards: 0, due: 0, buzzed_clusters: { [String(record.clues[0].cluster_id)]: 2 },
          buzzing: { buzzes: 2, correct: 1, accuracy: 0.5, median_correct_position: 0.4, power_rate: 1 } }
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
  }))
  render(
    <MemoryRouter initialEntries={['/topic/invisible-man']}>
      <Routes><Route path="/topic/:key" element={<TopicPage />} /></Routes>
    </MemoryRouter>,
  )
  expect(await screen.findByRole('heading', { level: 1, name: 'Invisible Man' })).toBeInTheDocument()
  const clues = screen.getByRole('heading', { name: /The clue hall/ }).parentElement!
  expect(within(clues).getByText('1. Ras the Exhorter')).toBeInTheDocument()
  expect(screen.getByRole('img', { name: 'Where each clue appears in questions' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'The Invisible Man' })).toBeInTheDocument()
  expect(await screen.findByText('50%')).toBeInTheDocument() // your accuracy
  for (const follow of screen.getAllByRole('button', { name: 'Follow' })) expect(follow).toBeEnabled() // entrance and exit
  // AI summary replaces the wiki lead when available
  expect(screen.getByText('Invisible Man is a novel by Ralph Ellison.')).toBeInTheDocument()
  expect(screen.getByRole('img', { name: 'First edition cover' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Public domain' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Ralph Ellison: A Biography' })).toBeInTheDocument()
  expect(screen.getByText('cited by Wikipedia')).toBeInTheDocument()
  expect(screen.getByText('Videos: coming soon.')).toBeInTheDocument()
  vi.unstubAllGlobals()
})

function content(status: 'ready' | 'partial') {
  const pending = { status: 'pending', payload: null, fetched_at: null }
  return {
    topic_id: 'Q1784288',
    status,
    sections: {
      wiki: { status: 'ok', fetched_at: '2026-10-10', payload: {
        title: 'Invisible Man', url: 'https://en.wikipedia.org/wiki/Invisible_Man',
        lead: 'Invisible Man is a novel by Ralph Ellison, published in 1952.', sections: [],
        license: 'CC BY-SA 4.0', license_url: 'https://creativecommons.org/licenses/by-sa/4.0/',
        attribution: 'Text from the Wikipedia article “Invisible Man”, by its contributors.' } },
      summary: { status: 'ok', fetched_at: '2026-10-10', payload: {
        summary: 'Invisible Man is a novel by Ralph Ellison.', hook: 'A nameless narrator searches for identity.',
        marked: [], source: null } },
      images: status === 'partial' ? pending : { status: 'ok', fetched_at: '2026-10-10', payload: { images: [{
        file: 'File:Invisible Man.jpg', url: 'https://upload.wikimedia.org/x.jpg', width: 400, height: 600,
        page: 'https://commons.wikimedia.org/wiki/File:Invisible_Man.jpg', caption: 'First edition cover',
        artist: 'E. McKnight Kauffer', license: 'Public domain', license_url: 'https://example.org/pd',
        attribution_required: false, is_main: true }] } },
      books: status === 'partial' ? pending : { status: 'ok', fetched_at: '2026-10-10', payload: {
        books: [{ title: 'Ralph Ellison: A Biography', author: 'Arnold Rampersad', year: 2007, isbn: null,
          cover: null, open_library: 'https://openlibrary.org/works/OL1W', cited: 2, source: 'cited' }],
        references: [{ name: 'Encyclopaedia Britannica', url: 'https://www.britannica.com/search?query=Invisible+Man' }] } },
      videos: { status: 'unavailable', fetched_at: '2026-10-10', payload: { reason: 'no key' } },
    },
  }
}

test('the topic page shows loading screen until all content is ready', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  let contentCalls = 0
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    let body: unknown = { detail: 'offline' }
    if (url.startsWith('/api/catalog/topics/')) body = record
    if (url.startsWith('/api/content/')) body = content(contentCalls++ === 0 ? 'partial' : 'ready')
    return new Response(JSON.stringify(body), {
      status: url.startsWith('/api/study/') ? 503 : 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }))
  render(
    <MemoryRouter initialEntries={['/topic/invisible-man']}>
      <Routes><Route path="/topic/:key" element={<TopicPage />} /></Routes>
    </MemoryRouter>,
  )
  expect(await screen.findByText('Curating this exhibit...')).toBeInTheDocument()
  await act(() => vi.advanceTimersByTimeAsync(3000))
  expect(await screen.findByRole('img', { name: 'First edition cover' })).toBeInTheDocument()
  expect(screen.queryByText('Curating this exhibit...')).not.toBeInTheDocument()
  expect(contentCalls).toBe(2)
  await act(() => vi.advanceTimersByTimeAsync(10000))
  expect(contentCalls).toBe(2) // stopped polling once ready
  vi.useRealTimers()
  vi.unstubAllGlobals()
})


test('show more loads the next five clues', async () => {
  const first = { ...record, n_clues: record.clues.length + 2 }
  const extra = [0, 1].map((i) => ({
    ...record.clues[0], rank: record.clues.length + 1 + i, cluster_id: 9000 + i, label: `Extra clue ${i}`,
  }))
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    calls.push(url)
    let body: unknown = { detail: 'offline' }
    if (url.startsWith('/api/catalog/topics/') && url.includes('/clues?')) body = extra
    else if (url.startsWith('/api/catalog/topics/')) body = first
    else if (url.startsWith('/api/content/')) body = content('ready')
    return new Response(JSON.stringify(body), {
      status: body && !(body as Record<string, unknown>).detail ? 200 : 503,
      headers: { 'Content-Type': 'application/json' },
    })
  }))
  render(
    <MemoryRouter initialEntries={['/topic/invisible-man']}>
      <Routes><Route path="/topic/:key" element={<TopicPage />} /></Routes>
    </MemoryRouter>,
  )
  fireEvent.click(await screen.findByRole('button', { name: 'Show 2 more' }))
  expect(await screen.findByText(`${record.clues.length + 2}. Extra clue 1`)).toBeInTheDocument()
  expect(calls.some((u) => u.endsWith(`/clues?offset=${record.clues.length}&limit=5`))).toBe(true)
  expect(screen.queryByRole('button', { name: /more$/ })).not.toBeInTheDocument()
  vi.unstubAllGlobals()
})
