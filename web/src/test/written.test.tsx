import { fireEvent, render, screen } from '@testing-library/react'
import type { WikiImage } from '../api/types'
import { chooseIllustrations } from '../lib/illustrations'
import { Summary } from '../components/Written'

function shot(file: string, caption = ''): WikiImage {
  return {
    file, url: `https://example.test/${file}`, width: 800, height: 600, page: null,
    caption, artist: null, license: 'CC BY-SA 4.0', license_url: null,
    attribution_required: false, is_main: false,
  }
}

test('summary clues are bold, with a one-line popup and a link to the full explanation', () => {
  render(
    <Summary
      summary={{
        hook: 'A man underground.',
        summary: 'First he fights in a [[3|battle royal]].\n\nThen he meets [[5|Mr. Norton]].',
        marked: [3, 5],
        source: { title: 'Invisible Man', url: 'https://en.wikipedia.org/wiki/Invisible_Man', license: 'CC BY-SA 4.0' },
      }}
      explanations={[{ rank: 3, label: 'battle royal', one_line: 'Blindfolded boys box for white men.', explanation: '…' }]}
    />,
  )
  expect(screen.getAllByText(/^(First|Then)/)).toHaveLength(2) // two paragraphs
  fireEvent.click(screen.getByRole('button', { name: 'battle royal' }))
  expect(screen.getByRole('tooltip')).toHaveTextContent('Blindfolded boys box for white men.')
  expect(screen.getByRole('link', { name: 'See more' })).toHaveAttribute('href', '#clue-3')
})

describe('special sections', () => {
  it('keeps the diagram and the example list, and drops the essay', async () => {
    const { Feature, ExhibitTimeline } = await import('../components/Special')
    const special = {
      timeline: { kind: 'discoveries', events: [{ year: -44, label: 'Caesar is killed', source: 'In 44 BC Caesar was killed.' }] },
      feature: {
        form: 'A handful', title: 'How a lens works', body: 'This essay should stay hidden.',
        dramatized: true,
        steps: [{ label: 'Light enters', detail: 'x' }, { label: 'Rays bend', detail: 'y' }],
        diagram_blurb: 'The diagram follows one ray from the air into the glass and back out again.',
        entries: [
          { name: 'Convex lens', text: 'Thicker in the middle, it brings rays to a point.' },
          { name: 'Focal length', text: 'The distance from the lens to that point.' },
        ],
      },
      source: { title: 'Lens', url: 'https://en.wikipedia.org/wiki/Lens' },
    }
    render(<><Feature special={special} /><ExhibitTimeline timeline={special.timeline} /></>)
    expect(screen.getByText('How a lens works')).toBeTruthy()
    expect(screen.getByText('Convex lens')).toBeTruthy()
    expect(screen.queryByText('Focal length')).toBeNull()
    expect(screen.getByRole('navigation', { name: 'Example navigation' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Next example' }))
    expect(screen.getByText('Focal length')).toBeTruthy()
    expect(screen.queryByText('Convex lens')).toBeNull()
    expect(screen.getByText('Rays bend')).toBeTruthy()
    expect(screen.getByText(/follows one ray/)).toBeTruthy()
    expect(screen.getByText('44 BCE')).toBeTruthy()
    expect(screen.queryByText(/essay should stay hidden/)).toBeNull()
    expect(screen.queryByText(/dramatized scene/)).toBeNull()
  })

  it('lists a handful of related things instead of one long essay', async () => {
    const { Feature } = await import('../components/Special')
    render(
      <Feature
        illustrations={{ Sidewinder: shot('File:Sidewinder.jpg', 'A horned viper') }}
        special={{
        timeline: { kind: 'events', events: [] },
        feature: {
          form: 'A handful', title: 'Six snakes', body: 'A leftover essay.', dramatized: false, steps: [],
          entries: [
            { name: 'King cobra', text: 'A long hooded snake that nests.' },
            { name: 'Sidewinder', text: 'It throws a loop of its body across the sand.' },
          ],
        },
        source: null,
      }} />,
    )
    expect(screen.getByText('Six snakes')).toBeTruthy()
    expect(screen.getByText('King cobra')).toBeTruthy()
    expect(screen.queryByText(/throws a loop/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Next example' }))
    expect(screen.getByText(/throws a loop/)).toBeTruthy()
    expect(screen.getByRole('img', { name: 'A horned viper' })).toBeTruthy()
    expect(screen.queryByText(/leftover essay/)).toBeNull()
    expect(screen.queryByText(/dramatized scene/)).toBeNull()
  })

  it('shows a picture on about two examples, spread through the list', () => {
    const names = ['King cobra', 'Sidewinder', 'Python', 'Taipan', 'Krait']
    const lookedUp = names.map((name) => ({ name, image: shot(`File:${name}.jpg`, name) }))
    const chosen = chooseIllustrations(names, lookedUp)
    expect(Object.keys(chosen)).toEqual(['King cobra', 'Krait'])

    const gallery = [
      shot('File:King cobra close.jpg', 'King cobra rearing'),
      shot('File:Python molurus.jpg', 'Indian python'),
      shot('File:Bungarus.jpg', 'A krait'),
    ]
    const filled = chooseIllustrations(
      names,
      [{ name: 'Sidewinder', image: shot('File:Sidewinder.jpg') }],
      gallery,
    )
    expect(Object.keys(filled).sort()).toEqual(['Krait', 'Sidewinder'])
  })
})

describe('the clue hall', () => {
  it('shows each explanation without a click, with the other clues it names in bold', async () => {
    const { ClueList } = await import('../components/ClueList')
    const heatmap = { position_hist: [], share_in_power: 0, share_last_line: 0, difficulty: {}, years: [null, null] as [null, null], trend: 'steady' as const }
    const clue = (rank: number, label: string) => ({
      rank, cluster_id: rank, label, text: `${label} in a question.`, examples: [], n_sets: 3,
      n_tossups: 3, median_position: 0.5, heatmap,
    })
    const explanations = [
      { rank: 1, label: 'Flower Wars', one_line: 'Ritual wars for captives.', explanation: 'Fought mostly against Tlaxcala for captives.' },
    ]
    render(<ClueList clues={[clue(1, 'Flower Wars'), clue(2, 'Tlaxcala')]} explanations={explanations} writing />)
    expect(screen.getByText(/Fought mostly against/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Tlaxcala' })).toBeTruthy() // bolded, with its popup
    expect(screen.getByText('Explanation being written…')).toBeTruthy() // clue 2 isn't written yet
  })
})
