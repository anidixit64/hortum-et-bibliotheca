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
  expect(screen.getByRole('link', { name: '“Invisible Man”' })).toBeInTheDocument()
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
})
