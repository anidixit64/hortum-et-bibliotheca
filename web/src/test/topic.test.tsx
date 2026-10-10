import { render, screen, within } from '@testing-library/react'
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
  const clues = screen.getByRole('heading', { name: 'Clues worth knowing' }).parentElement!
  expect(within(clues).getByText('1. Ras the Exhorter')).toBeInTheDocument()
  expect(screen.getByRole('img', { name: 'Where each clue appears in questions' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Ralph Ellison' })).toHaveAttribute('href', '/topic/Q299965')
  expect(screen.getByRole('link', { name: 'The Invisible Man' })).toBeInTheDocument()
  expect(await screen.findByText('50%')).toBeInTheDocument() // your accuracy
  expect(screen.getByRole('button', { name: 'Follow' })).toBeEnabled()
  vi.unstubAllGlobals()
})
