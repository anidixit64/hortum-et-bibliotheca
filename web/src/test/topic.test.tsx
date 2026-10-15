import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { vi } from 'vitest'
import type { Clue } from '../api/types'
import { sortedClues } from '../components/ClueList'
import { TopicPage } from '../pages/TopicPage'
import { App } from '../App'
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
  expect(screen.getByRole('heading', { level: 3, name: 'Ras the Exhorter' })).toBeInTheDocument()
  expect(screen.getByRole('img', { name: 'Where each clue appears in questions' })).toBeInTheDocument()
  const hall = document.getElementById('room-clues')
  expect(hall?.closest('.museum-layout')).toBeNull()
  expect(hall?.querySelector('h2')?.textContent).toContain('The clue hall')
  expect(document.querySelector('.exhibit-where h2')?.textContent).toBe('Where the clues come up')
  expect(screen.getByRole('link', { name: 'The Invisible Man' })).toBeInTheDocument()
  expect(await screen.findByText('50%')).toBeInTheDocument() // your accuracy
  for (const follow of screen.getAllByRole('button', { name: 'Follow' })) expect(follow).toBeEnabled() // entrance and exit
  // AI summary replaces the wiki lead when available
  expect(screen.getByText('Invisible Man is a novel by Ralph Ellison.')).toBeInTheDocument()
  expect(screen.getByRole('img', { name: 'First edition cover' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Public domain' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Ralph Ellison: A Biography' })).toBeInTheDocument()
  expect(screen.getByText('Videos: coming soon.')).toBeInTheDocument()
  vi.unstubAllGlobals()
})

function content(status: 'ready' | 'partial'): {
  topic_id: string
  status: 'ready' | 'partial'
  sections: Record<string, { status: string; fetched_at: string | null; payload: unknown }>
} {
  const pending = { status: 'pending', payload: null, fetched_at: null }
  return {
    topic_id: 'Q1784288',
    status,
    sections: {
      wiki: { status: 'ok', fetched_at: '2026-10-10', payload: {
        title: 'Invisible Man', url: 'https://en.wikipedia.org/wiki/Invisible_Man',
        lead: 'Invisible Man is a novel by Ralph Ellison, published in 1952.',
        sections: [{ heading: 'Plot', text: 'The narrator lives underground and tells his story from a basement full of light bulbs.' }],
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

test('examples step through one at a time, with pictures on about two of them', async () => {
  const ready = content('ready')
  ready.sections.special = {
    status: 'ok',
    fetched_at: '2026-10-10',
    payload: {
      timeline: { kind: 'events', events: [] },
      feature: {
        form: 'A handful', title: 'Six moments', body: '', dramatized: false,
        diagram_title: 'How a mask holds a self',
        steps: [
          { label: 'A role', detail: 'Someone is handed a part.' },
          { label: 'The mask', detail: 'The part starts to feel like a face.' },
        ],
        diagram_blurb: 'Start with a costume. The hard part is what remains when it comes off.',
        entries: [
          { name: 'Battle royal', text: 'Boys box blindfolded.' },
          { name: 'The prologue', text: 'He speaks from a hole full of light.' },
          { name: 'Ras the Destroyer', text: 'A Harlem figure on a horse.' },
        ],
      },
      source: null,
    },
  }
  const image = (file: string, caption: string) => ({
    file, url: `https://example.test/${file}`, width: 800, height: 600, page: null, caption,
    artist: null, license: 'CC BY-SA 4.0', license_url: null, attribution_required: false, is_main: false,
  })
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    let body: unknown = {
      topic_id: 'Q1784288', followed: false, cards: 0, due: 0, buzzed_clusters: {},
      buzzing: { buzzes: 0, correct: 0, accuracy: null, median_correct_position: null, power_rate: null },
    }
    if (url.includes('example-images')) {
      body = {
        images: [
          { name: 'Battle royal', image: image('File:Ring.jpg', 'A boxing ring') },
          { name: 'Ras the Destroyer', image: image('File:Rider.jpg', 'A rider') },
        ],
      }
    } else if (url.includes('/lookup')) body = {}
    else if (url.startsWith('/api/catalog/topics/')) body = record
    else if (url.startsWith('/api/content/')) body = ready
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
  }))
  render(
    <MemoryRouter initialEntries={['/topic/invisible-man']}>
      <Routes><Route path="/topic/:key" element={<TopicPage />} /></Routes>
    </MemoryRouter>,
  )
  const feature = await screen.findByRole('heading', { name: 'Six moments' })
  const box = feature.closest('#room-feature')
  expect(box?.closest('.museum-layout')).toBeNull()
  expect(document.getElementById('room-introduction')?.closest('.museum-center')).not.toBeNull()
  expect(await within(box as HTMLElement).findByRole('img', { name: 'A boxing ring' })).toBeInTheDocument()
  expect(within(box as HTMLElement).queryByText(/hole full of light/)).not.toBeInTheDocument()
  fireEvent.click(within(box as HTMLElement).getByRole('button', { name: 'Next example' }))
  expect(within(box as HTMLElement).getByText(/hole full of light/)).toBeInTheDocument()
  expect(within(box as HTMLElement).queryByRole('img')).not.toBeInTheDocument()
  fireEvent.click(within(box as HTMLElement).getByRole('button', { name: 'Next example' }))
  expect(within(box as HTMLElement).getByRole('img', { name: 'A rider' })).toBeInTheDocument()
  expect(within(box as HTMLElement).queryByText('The mask')).not.toBeInTheDocument()
  const diagram = document.getElementById('room-diagram')
  expect(diagram).toBeTruthy()
  expect(diagram?.closest('#room-feature')).toBeNull()
  expect(screen.queryByText(/costume/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /How a mask holds a self/ }))
  expect(screen.getByText(/costume/)).toBeInTheDocument()
  vi.unstubAllGlobals()
})

test('the topic page shows the loading screen until generated content is ready', async () => {
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
  expect(screen.queryByRole('heading', { level: 1, name: 'Invisible Man' })).not.toBeInTheDocument()
  await act(() => vi.advanceTimersByTimeAsync(3000))
  expect(await screen.findByRole('img', { name: 'First edition cover' })).toBeInTheDocument()
  expect(screen.queryByText('Curating this exhibit...')).not.toBeInTheDocument()
  expect(contentCalls).toBe(2)
  await act(() => vi.advanceTimersByTimeAsync(10000))
  expect(contentCalls).toBe(2) // stopped polling once ready
  vi.useRealTimers()
  vi.unstubAllGlobals()
})


test('sort toggle switches between frequency and rarity ordering', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const body = url.startsWith('/api/catalog/topics/')
      ? record
      : url.startsWith('/api/content/')
        ? content('ready')
        : { topic_id: 'Q1784288', followed: false, cards: 0, due: 0, buzzed_clusters: {},
          buzzing: { buzzes: 0, correct: 0, accuracy: null, median_correct_position: null, power_rate: null } }
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
  }))
  render(
    <MemoryRouter initialEntries={['/topic/invisible-man']}>
      <Routes><Route path="/topic/:key" element={<TopicPage />} /></Routes>
    </MemoryRouter>,
  )
  const freq = await screen.findByRole('button', { name: 'Frequency' })
  const rarity = screen.getByRole('button', { name: 'Rarity' })
  expect(screen.getByRole('button', { name: 'Position' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Descending' })).toBeInTheDocument()
  expect(freq.className).toContain('active')
  expect(rarity.className).not.toContain('active')
  // Switch to rarity
  fireEvent.click(rarity)
  expect(rarity.className).toContain('active')
  expect(freq.className).not.toContain('active')
  vi.unstubAllGlobals()
})

test('frequency, rarity, and position follow the chosen direction', () => {
  const base = record.clues[0]
  const clues = [1, 2, 3].map((i) => ({
    ...base,
    rank: i,
    cluster_id: i,
    n_questions: i * 10,
    n_tossups: i * 10,
    median_position: i / 10,
    mean_position: i / 10,
  })) as unknown as Clue[]
  expect(sortedClues(clues, 'frequency', null).map((c) => c.rank)).toEqual([3, 2, 1])
  expect(sortedClues(clues, 'frequency', null, 'asc').map((c) => c.rank)).toEqual([1, 2, 3])
  expect(sortedClues(clues, 'rarity', null).map((c) => c.rank)).toEqual([1, 2, 3])
  expect(sortedClues(clues, 'rarity', null, 'desc').map((c) => c.rank)).toEqual([3, 2, 1])
  expect(sortedClues(clues, 'position', null).map((c) => c.rank)).toEqual([1, 2, 3])
  expect(sortedClues(clues, 'position', null, 'desc').map((c) => c.rank)).toEqual([3, 2, 1])
})

test('rarity orders the cleaned list, and show more walks that order', async () => {
  const base = record.clues[0]
  const clues = Array.from({ length: 12 }, (_, i) => ({
    ...base,
    rank: i + 1,
    cluster_id: 500 + i,
    label: `Clue ${i + 1}`,
    earliest_position: i === 11 ? 0.02 : 0.9,
    median_position: 0.5,
    n_questions: 30 - i,
  }))
  const cleaned = clues.map((c) => ({
    rank: c.rank,
    label: c.label,
    n_questions: c.n_questions,
    clue_ids: [c.cluster_id],
    spellings: [c.label],
  }))
  const ready = content('ready')
  ready.sections = {
    ...ready.sections,
    clues: {
      status: 'ok',
      fetched_at: '2026-10-10',
      payload: { clues: cleaned },
    },
    explanations: {
      status: 'ok',
      fetched_at: '2026-10-10',
      payload: {
        clues: cleaned.map((c) => ({
          rank: c.rank,
          label: c.label,
          one_line: `${c.label} line`,
          explanation: `${c.label} explained.`,
        })),
      },
    },
  }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    let body: unknown = {
      topic_id: 'Q1784288', followed: false, cards: 0, due: 0, buzzed_clusters: {},
      buzzing: { buzzes: 0, correct: 0, accuracy: null, median_correct_position: null, power_rate: null },
    }
    if (url.includes('/clues?')) body = []
    else if (url.includes('/lookup')) body = {}
    else if (url.startsWith('/api/catalog/topics/')) body = { ...record, clues, n_clues: 12 }
    else if (url.startsWith('/api/content/')) body = ready
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
  }))
  render(
    <MemoryRouter initialEntries={['/topic/invisible-man']}>
      <Routes><Route path="/topic/:key" element={<TopicPage />} /></Routes>
    </MemoryRouter>,
  )
  expect(await screen.findByRole('heading', { level: 3, name: 'Clue 1' })).toBeInTheDocument()
  expect(within(screen.getByLabelText('Clue navigation')).getByText('1 of 10')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Rarity' }))
  expect(screen.getByRole('heading', { level: 3, name: 'Clue 12' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Show 2 more' }))
  expect(within(screen.getByLabelText('Clue navigation')).getByText('1 of 12')).toBeInTheDocument()
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
  const nav = screen.getByLabelText('Clue navigation')
  expect(await within(nav).findByText(`1 of ${record.clues.length + 2}`)).toBeInTheDocument()
  expect(calls.some((u) => u.endsWith(`/clues?offset=${record.clues.length}&limit=5`))).toBe(true)
  expect(screen.queryByRole('button', { name: /more$/ })).not.toBeInTheDocument()
  vi.unstubAllGlobals()
})

test('non-AI opens the article without generation, and AI starts in place', async () => {
  localStorage.setItem('museo-ai', 'off')
  const urls: string[] = []
  const study = {
    topic_id: 'Q1784288', followed: false, cards: 0, due: 0, buzzed_clusters: {},
    buzzing: { buzzes: 0, correct: 0, accuracy: null, median_correct_position: null, power_rate: null },
  }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    urls.push(url)
    let body: unknown = study
    if (url.startsWith('/api/catalog/topics/')) body = record
    else if (url.includes('generate=false')) body = content('ready')
    else if (url.startsWith('/api/content/')) {
      const partial = content('partial')
      partial.sections.summary = { status: 'pending', payload: null, fetched_at: null }
      partial.sections.facts = { status: 'pending', payload: null, fetched_at: null }
      body = partial
    }
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
  }))
  render(
    <MemoryRouter initialEntries={['/topic/invisible-man']}>
      <App />
    </MemoryRouter>,
  )
  expect(await screen.findByText(/published in 1952/)).toBeInTheDocument()
  expect(screen.getByText('Plot')).toBeInTheDocument()
  expect(screen.queryByText('exhibit generating...')).not.toBeInTheDocument()
  expect(screen.queryByText('Invisible Man is a novel by Ralph Ellison.')).not.toBeInTheDocument()
  const reading = document.getElementById('room-reading')
  expect(reading?.querySelector('a')?.textContent).toBe('Ralph Ellison: A Biography')
  expect(reading?.closest('.museum-layout')).toBeNull()
  expect(urls.some((u) => u.includes('generate=false'))).toBe(true)
  expect(urls.some((u) => u.includes('generate=true'))).toBe(false)

  fireEvent.click(screen.getByRole('button', { name: 'Menu' }))
  fireEvent.click(screen.getByRole('switch', { name: 'AI writing' }))
  expect(await screen.findAllByText('exhibit generating...')).not.toHaveLength(0)
  expect(screen.getByRole('heading', { level: 1, name: 'Invisible Man' })).toBeInTheDocument()
  expect(urls.some((u) => u.includes('generate=true'))).toBe(true)
  localStorage.removeItem('museo-ai')
  vi.unstubAllGlobals()
})

test('sidebars hold the photos, facts stay a checkerboard, and clues survive a bad cleanup', async () => {
  localStorage.setItem('museo-ai', 'on')
  const ready = content('ready')
  const shot = (file: string, caption: string) => ({
    file, url: `https://example.test/${file}`, width: 800, height: 600, page: null, caption,
    artist: null, license: 'CC BY-SA 4.0', license_url: null, attribution_required: false, is_main: false,
  })
  const images = Array.from({ length: 10 }, (_, i) => shot(`File:${i}.jpg`, `Caption ${i}`))
  const tone = {
    bg: '#f4ead8', surface: '#fff8ee', text: '#24161f', muted: '#5c4a42',
    accent: '#8d4a36', accent2: '#c9a227', accent_soft: '#f0ddd2', header_tint: '#f4ead8',
  }
  ready.sections.images = { status: 'ok', fetched_at: '2026-10-10', payload: { images } }
  ready.sections.facts = {
    status: 'ok', fetched_at: '2026-10-10',
    payload: { facts: [1, 2, 3, 4].map((i) => ({ fact: `Fact ${i} about the novel.`, source_sentence: 'He lives underground.' })) },
  }
  ready.sections.theme = {
    status: 'ok', fetched_at: '2026-10-10',
    payload: {
      light: tone, dark: tone, font: 'classical-serif', header: null,
      rationale: 'Candlelight and basement gold were chosen because the novel lives underground.',
    },
  }
  ready.sections.clues = {
    status: 'ok', fetched_at: '2026-10-10',
    payload: { clues: [{ rank: 1, label: 'Gone', n_questions: 4, clue_ids: [999999], spellings: ['Gone'] }] },
  }
  ready.sections.books = {
    status: 'ok', fetched_at: '2026-10-10',
    payload: {
      books: [0, 1, 2].map((i) => ({
        title: `Shelf Book ${i}`, author: 'A. Writer', year: 2000 + i, isbn: '9780393000000',
        cover: null, open_library: `https://openlibrary.org/works/OL${i}W`, cited: 1, source: 'cited',
        publisher: 'W. W. Norton & Company',
      })),
      references: [],
    },
  }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    let body: unknown = {
      topic_id: 'Q1784288', followed: false, cards: 0, due: 0, buzzed_clusters: {},
      buzzing: { buzzes: 0, correct: 0, accuracy: null, median_correct_position: null, power_rate: null },
    }
    if (String(url).includes('/clues')) body = []
    else if (String(url).includes('/lookup')) body = {}
    else if (String(url).startsWith('/api/catalog/topics/')) body = record
    else if (String(url).startsWith('/api/content/')) body = ready
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
  }))
  render(
    <MemoryRouter initialEntries={['/topic/invisible-man']}>
      <Routes><Route path="/topic/:key" element={<TopicPage />} /></Routes>
    </MemoryRouter>,
  )
  expect(await screen.findByRole('heading', { level: 3, name: 'Ras the Exhorter' })).toBeInTheDocument()
  expect(screen.queryByText(/Not asked often enough/)).not.toBeInTheDocument()
  expect(screen.getAllByRole('heading', { name: 'In the collection' })).toHaveLength(6)
  const leftHeads = [...document.querySelectorAll('.museum-left h3')].map((node) => node.textContent)
  const rightHeads = [...document.querySelectorAll('.museum-right h3')].map((node) => node.textContent)
  expect(leftHeads[0]).toBe('Map')
  expect(leftHeads).toEqual(['Map', 'In the collection', 'Screening room', 'In the collection', 'In the collection'])
  expect(rightHeads[0]).toBe('Timeline')
  expect(rightHeads.filter((title) => title === 'In the collection')).toHaveLength(3)
  expect(screen.getByText('Caption 0')).toBeInTheDocument()
  expect(screen.getByText('Caption 1')).toBeInTheDocument()
  const gallery = document.querySelector('.exhibit-gallery')
  expect(gallery?.textContent).toContain('Caption 8')
  expect(gallery?.textContent).toContain('Caption 9')
  const plaques = [...document.querySelectorAll('.plaque')]
  expect(plaques).toHaveLength(4)
  expect(plaques[0].textContent).toContain('Fact 1')
  expect(document.querySelector('.plaques img')).toBeNull()
  expect(document.querySelectorAll('.books li')).toHaveLength(2)
  expect(document.querySelector('.books img')?.getAttribute('src')).toContain('9780393000000')
  fireEvent.click(screen.getByRole('button', { name: 'Color palette' }))
  expect(screen.getByText(/Candlelight and basement gold/)).toBeInTheDocument()
  localStorage.removeItem('museo-ai')
  vi.unstubAllGlobals()
})
