import { fireEvent, render, screen } from '@testing-library/react'
import { Summary } from '../components/Written'

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
  it('shows the feature, a dramatized note, the step diagram and the grounded timeline', async () => {
    const { Feature, ExhibitTimeline } = await import('../components/Special')
    const special = {
      timeline: { kind: 'events', events: [{ year: -44, label: 'Caesar is killed', source: 'In 44 BC Caesar was killed.' }] },
      feature: {
        form: 'Be there', title: 'The Ides', body: 'First.\n\nSecond.', dramatized: true,
        steps: [{ label: 'Senate meets', detail: 'x' }, { label: 'Daggers', detail: 'y' }],
      },
      source: { title: 'Julius Caesar', url: 'https://en.wikipedia.org/wiki/Julius_Caesar' },
    }
    render(<><Feature special={special} /><ExhibitTimeline timeline={special.timeline} /></>)
    expect(screen.getByText('The Ides')).toBeTruthy()
    expect(screen.getByText(/dramatized scene/)).toBeTruthy()
    expect(screen.getByText('Daggers')).toBeTruthy()
    expect(screen.getByText('44 BCE')).toBeTruthy()
  })

  it('lists a handful of related things instead of one long essay', async () => {
    const { Feature } = await import('../components/Special')
    render(
      <Feature special={{
        timeline: { kind: 'events', events: [] },
        feature: {
          form: 'A handful', title: 'Six snakes', body: '', dramatized: false, steps: [],
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
    expect(screen.getByText(/throws a loop/)).toBeTruthy()
    expect(screen.queryByText(/dramatized scene/)).toBeNull()
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
