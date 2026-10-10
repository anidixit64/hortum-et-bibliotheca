import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { DueCard } from '../api/types'

const RATINGS = [
  { value: 1, label: 'Again' },
  { value: 2, label: 'Hard' },
  { value: 3, label: 'Good' },
  { value: 4, label: 'Easy' },
] as const

export function ReviewPage({ onReviewed }: { onReviewed?: () => void }) {
  const [cards, setCards] = useState<DueCard[] | null>(null)
  const [flipped, setFlipped] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.due().then(setCards).catch((e: Error) => setError(e.message))
  }, [])

  if (error) return <p className="error">{error}</p>
  if (!cards) return <p className="muted">Loading…</p>
  if (!cards.length)
    return (
      <div className="card">
        <p>Nothing due. Follow topics to make cards, or come back tomorrow.</p>
        <Link to="/">Find a topic</Link>
      </div>
    )

  const [card, ...rest] = cards
  const rate = async (rating: 1 | 2 | 3 | 4) => {
    await api.review(card.card_id, rating)
    setFlipped(false)
    setCards(rest)
    onReviewed?.()
  }

  return (
    <div className="card">
      <p className="muted small">
        {cards.length} due · {card.kind === 'missed' ? 'from a missed buzz' : card.kind === 'reverse' ? 'name the clues' : 'clue → answer'} ·{' '}
        <Link to={`/topic/${encodeURIComponent(card.topic_id)}`}>topic</Link>
      </p>
      <div className="flashcard">
        <div>{card.front}</div>
        {flipped && <div className="back">{card.back}</div>}
      </div>
      <div className="ratings">
        {flipped ? (
          RATINGS.map((r) => (
            <button key={r.value} className={r.value === 3 ? 'primary' : ''} onClick={() => rate(r.value)}>
              {r.label}
            </button>
          ))
        ) : (
          <button className="primary" onClick={() => setFlipped(true)}>Show answer</button>
        )}
      </div>
    </div>
  )
}
