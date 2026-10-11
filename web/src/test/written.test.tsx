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
