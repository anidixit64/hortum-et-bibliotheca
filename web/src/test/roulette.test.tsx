import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { vi } from 'vitest'
import { buildStrip, landingIndex, reelOffset, topicBlurb, WINDOW } from '../lib/roulette'
import type { RouletteTopic } from '../api/types'
import { ExplorePage } from '../pages/ExplorePage'
import { HomePage } from '../pages/HomePage'

const topics: RouletteTopic[] = [
  { topic_id: 'Q1', name: 'Invisible Man', category: 'Literature', description: 'A 1952 novel.', count: 12 },
  { topic_id: 'Q2', name: 'Mercury', category: 'Science', description: 'The innermost planet.', count: 4 },
  { topic_id: 'Q3', name: 'Gettysburg', category: 'History', description: 'An 1863 battle.', count: 9 },
]

function topic(id: string): RouletteTopic {
  return topics.find((item) => item.topic_id === id) as RouletteTopic
}

test('the reel stops with the chosen topic on the center line', () => {
  const strip = buildStrip(topics, 'Q2')
  const index = landingIndex(strip)
  expect(strip[index]).toEqual(topic('Q2'))
  expect(index).toBeGreaterThan(topics.length * 4)
  const cell = 104
  const windowPx = WINDOW * cell
  expect(reelOffset(index, windowPx, cell)).toBe(windowPx / 2 - cell / 2 - index * cell)
  expect(topicBlurb({ ...topic('Q3'), description: '  An 1863 battle. ' })).toBe('An 1863 battle.')
  expect(topicBlurb({ ...topic('Q3'), description: null })).toMatch(/History/)
})

test('the open color wheel stays gray until a palette is hovered', () => {
  render(<MemoryRouter><HomePage /></MemoryRouter>)
  fireEvent.mouseEnter(document.querySelector('.palette-footer') as Element)
  const color = document.querySelector('.palette-wheel-ring-color') as HTMLElement
  expect(color.className).not.toContain('on')
  expect((document.querySelector('.palette-wheel-ring') as HTMLElement).style.background).toContain('rgb(213, 213, 213)')
  fireEvent.mouseEnter(screen.getByRole('button', { name: 'Terracotta Exhibit theme' }))
  expect(color.className).toContain('on')
  expect(color.style.background).toContain('rgb(141, 74, 54)')
  expect(screen.getByText('earthy and welcoming')).toBeInTheDocument()
  expect(screen.getByText('Terracotta Exhibit')).toBeInTheDocument()
})

test('the randomizer spins onto a topic over the explore page', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    let body: unknown = []
    if (String(url).includes('/explore/roulette')) body = topics
    else if (String(url).includes('/explore/top')) body = []
    else if (String(url).includes('/thumbnails')) body = {}
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
  }))
  render(
    <MemoryRouter initialEntries={['/explore/american-literature']}>
      <Routes><Route path="/explore/:slug" element={<ExplorePage />} /></Routes>
    </MemoryRouter>,
  )
  fireEvent.click(await screen.findByRole('button', { name: 'Randomizer' }))
  expect(document.querySelector('.roulette-backdrop')).toBeTruthy()
  const learn = await screen.findByRole('button', { name: 'Learn more' })
  expect(learn.closest('a')?.getAttribute('href')).toMatch(/^\/topic\/Q[123]$/)
  expect(screen.getByText(/1952 novel|innermost planet|1863 battle/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '← Explore' }))
  expect(screen.queryByRole('dialog', { name: 'Random topic' })).not.toBeInTheDocument()
  vi.unstubAllGlobals()
})
