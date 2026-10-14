import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { DueCard } from '../api/types'

const RATINGS = [
  { value: 1, label: 'Again', color: 'var(--bad)' },
  { value: 2, label: 'Hard', color: 'var(--warn)' },
  { value: 3, label: 'Good', color: 'var(--accent)' },
  { value: 4, label: 'Easy', color: 'var(--good)' },
] as const

const COLLECTIONS_KEY = 'museo.collections'
const CARD_COLLECTIONS_KEY = 'museo.cardCollections'

function readCollections(): string[] {
  try { return JSON.parse(localStorage.getItem(COLLECTIONS_KEY) || '[]') } catch { return [] }
}
function saveCollections(c: string[]) {
  try { localStorage.setItem(COLLECTIONS_KEY, JSON.stringify(c)) } catch {}
}
function readCardCollections(): Record<string, string[]> {
  try { return JSON.parse(localStorage.getItem(CARD_COLLECTIONS_KEY) || '{}') } catch { return {} }
}
function saveCardCollections(m: Record<string, string[]>) {
  try { localStorage.setItem(CARD_COLLECTIONS_KEY, JSON.stringify(m)) } catch {}
}

export function ReviewPage({ onReviewed }: { onReviewed?: () => void }) {
  const [cards, setCards] = useState<DueCard[] | null>(null)
  const [flipped, setFlipped] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [collections, setCollections] = useState(readCollections)
  const [newCollName, setNewCollName] = useState('')
  const [showCollections, setShowCollections] = useState(false)
  const [selectedCollection, setSelectedCollection] = useState<string | null>(null)
  const [cardCollections, setCardCollections] = useState(readCardCollections)

  useEffect(() => {
    if (selectedCollection) {
      const cardIds = cardCollections[selectedCollection] || []
      if (cardIds.length === 0) {
        setCards([])
        return
      }
      api.due(500).then(all => {
        const inColl = all.filter(c => cardIds.includes(c.card_id))
        setCards(inColl)
      }).catch((e: Error) => setError(e.message))
    } else {
      api.due().then(setCards).catch((e: Error) => setError(e.message))
    }
  }, [selectedCollection, cardCollections])

  const createCollection = () => {
    const name = newCollName.trim()
    if (!name || collections.includes(name)) return
    const updated = [...collections, name]
    setCollections(updated)
    saveCollections(updated)
    setNewCollName('')
  }

  const deleteCollection = (name: string) => {
    setCollections(c => { const u = c.filter(n => n !== name); saveCollections(u); return u })
    setCardCollections(m => { const u = { ...m }; delete u[name]; saveCardCollections(u); return u })
    if (selectedCollection === name) setSelectedCollection(null)
  }

  const addCardToCollection = (cardId: string, collName: string) => {
    setCardCollections(m => {
      const arr = m[collName] || []
      if (arr.includes(cardId)) return m
      const u = { ...m, [collName]: [...arr, cardId] }
      saveCardCollections(u)
      return u
    })
  }

  const removeCardFromCollection = (cardId: string, collName: string) => {
    setCardCollections(m => {
      const arr = (m[collName] || []).filter(id => id !== cardId)
      const u = { ...m, [collName]: arr }
      saveCardCollections(u)
      return u
    })
  }

  if (error) return <p className="error">{error}</p>
  if (!cards) return <p className="muted">Loading…</p>

  return (
    <div className="review-page">
      <h1 className="review-title">Review</h1>

      <div className="review-layout">
        {/* ── Sidebar: collections ── */}
        <aside className="review-sidebar">
          <div className="sidebar-card">
            <h3 className="sidebar-title">Collections</h3>
            <button
              className={`coll-filter-btn${selectedCollection === null ? ' active' : ''}`}
              onClick={() => setSelectedCollection(null)}
            >
              All due cards
            </button>
            {collections.map(c => (
              <div key={c} className="coll-row">
                <button
                  className={`coll-filter-btn${selectedCollection === c ? ' active' : ''}`}
                  onClick={() => setSelectedCollection(c)}
                >
                  {c}
                  <span className="coll-count">{(cardCollections[c] || []).length}</span>
                </button>
                <button className="coll-delete" onClick={() => deleteCollection(c)} aria-label={`Delete ${c}`}>×</button>
              </div>
            ))}
            <div className="coll-create">
              <input
                type="text"
                placeholder="New collection…"
                value={newCollName}
                onChange={e => setNewCollName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && createCollection()}
                className="coll-input"
              />
              <button className="coll-add-btn" onClick={createCollection} disabled={!newCollName.trim()}>+</button>
            </div>
          </div>
        </aside>

        {/* ── Main card area ── */}
        <div className="review-center">
          {!cards.length ? (
            <div className="review-empty">
              <p>{selectedCollection ? `No cards in "${selectedCollection}" are due.` : 'Nothing due. Follow topics to make cards, or come back tomorrow.'}</p>
              <Link to="/">Find a topic</Link>
            </div>
          ) : (
            <ReviewCard
              card={cards[0]}
              remaining={cards.length}
              flipped={flipped}
              onFlip={() => setFlipped(true)}
              onRate={async (rating) => {
                await api.review(cards[0].card_id, rating)
                setFlipped(false)
                setCards(cards.slice(1))
                onReviewed?.()
              }}
              collections={collections}
              cardCollections={cardCollections}
              onAddToCollection={addCardToCollection}
              onRemoveFromCollection={removeCardFromCollection}
              onToggleCollections={() => setShowCollections(!showCollections)}
              showCollections={showCollections}
            />
          )}
        </div>
      </div>
    </div>
  )
}

function ReviewCard({
  card, remaining, flipped, onFlip, onRate, collections, cardCollections,
  onAddToCollection, onRemoveFromCollection, onToggleCollections, showCollections,
}: {
  card: DueCard
  remaining: number
  flipped: boolean
  onFlip: () => void
  onRate: (r: 1 | 2 | 3 | 4) => void
  collections: string[]
  cardCollections: Record<string, string[]>
  onAddToCollection: (cardId: string, coll: string) => void
  onRemoveFromCollection: (cardId: string, coll: string) => void
  onToggleCollections: () => void
  showCollections: boolean
}) {
  return (
    <>
      <p className="review-meta muted small">
        {remaining} due · {card.kind === 'missed' ? 'from a missed buzz' : card.kind === 'reverse' ? 'name the clues' : 'clue → answer'} ·{' '}
        <Link to={`/topic/${encodeURIComponent(card.topic_id)}`}>topic</Link>
      </p>

      <div className={`flip-card${flipped ? ' flipped' : ''}`} onClick={() => !flipped && onFlip()}>
        <div className="flip-card-inner">
          <div className="flip-card-front">
            <div className="flip-card-content">
              <p className="flip-card-text">{card.front}</p>
              {!flipped && <p className="flip-card-hint muted small">Click to reveal</p>}
            </div>
          </div>
          <div className="flip-card-back">
            <div className="flip-card-content">
              <p className="flip-card-text flip-card-answer">{card.back}</p>
            </div>
          </div>
        </div>
      </div>

      <div className="review-actions">
        {flipped ? (
          <div className="review-ratings">
            {RATINGS.map(r => (
              <button
                key={r.value}
                className="rating-btn"
                style={{ '--rating-color': r.color } as React.CSSProperties}
                onClick={() => onRate(r.value)}
              >
                {r.label}
              </button>
            ))}
          </div>
        ) : (
          <button className="primary review-show-btn" onClick={onFlip}>Show answer</button>
        )}
      </div>

      {collections.length > 0 && (
        <div className="review-coll-assign">
          <button className="review-coll-toggle" onClick={onToggleCollections}>
            {showCollections ? 'Hide' : 'Add to collection'}
          </button>
          {showCollections && (
            <div className="review-coll-list">
              {collections.map(c => {
                const inColl = (cardCollections[c] || []).includes(card.card_id)
                return (
                  <label key={c} className="review-coll-check">
                    <input
                      type="checkbox"
                      checked={inColl}
                      onChange={() => inColl
                        ? onRemoveFromCollection(card.card_id, c)
                        : onAddToCollection(card.card_id, c)
                      }
                    />
                    {c}
                  </label>
                )
              })}
            </div>
          )}
        </div>
      )}
    </>
  )
}
