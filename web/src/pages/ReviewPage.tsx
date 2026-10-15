import { useCallback, useEffect, useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { api, type CardFilter } from '../api/client'
import type { DueCard, FollowedTopic, Stats } from '../api/types'
import { categoryNames, subcategoriesOf } from '../lib/categories'
import { percent } from '../lib/format'

const RATINGS = [
  { value: 1, label: 'Again', color: 'var(--bad)' },
  { value: 2, label: 'Hard', color: 'var(--warn)' },
  { value: 3, label: 'Good', color: 'var(--accent)' },
  { value: 4, label: 'Easy', color: 'var(--good)' },
] as const

const DIFFICULTY_LABELS: Record<number, string> = {
  0: 'MS', 1: '1', 2: '2', 3: '3', 4: '4',
  5: '5', 6: '6', 7: '7', 8: '8', 9: '9', 10: 'Open',
}

const COLLECTIONS_KEY = 'museo.collections'
const CARD_COLLECTIONS_KEY = 'museo.cardCollections'

function readCollections(): string[] {
  try { return JSON.parse(localStorage.getItem(COLLECTIONS_KEY) || '[]') } catch { return [] }
}
function saveCollections(c: string[]) {
  try { localStorage.setItem(COLLECTIONS_KEY, JSON.stringify(c)) } catch { /* private mode */ }
}
function readCardCollections(): Record<string, string[]> {
  try { return JSON.parse(localStorage.getItem(CARD_COLLECTIONS_KEY) || '{}') } catch { return {} }
}
function saveCardCollections(m: Record<string, string[]>) {
  try { localStorage.setItem(CARD_COLLECTIONS_KEY, JSON.stringify(m)) } catch { /* private mode */ }
}

export function ReviewPage({ onReviewed }: { onReviewed?: () => void }) {
  const [cards, setCards] = useState<DueCard[] | null>(null)
  const [library, setLibrary] = useState<DueCard[] | null>(null)
  const [flipped, setFlipped] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [collections, setCollections] = useState(readCollections)
  const [newCollName, setNewCollName] = useState('')
  const [showCollections, setShowCollections] = useState(false)
  const [selectedCollection, setSelectedCollection] = useState<string | null>(null)
  const [cardCollections, setCardCollections] = useState(readCardCollections)
  const [category, setCategory] = useState('')
  const [subcategory, setSubcategory] = useState('')
  const [diffMin, setDiffMin] = useState<number | undefined>()
  const [diffMax, setDiffMax] = useState<number | undefined>()
  const [browsing, setBrowsing] = useState(false)
  const [stats, setStats] = useState<Stats | null>(null)
  const [followed, setFollowed] = useState<FollowedTopic[]>([])

  const filing = useCallback((): CardFilter => ({
    category: category || undefined,
    subcategory: subcategory || undefined,
    difficultyMin: diffMin,
    difficultyMax: diffMax,
  }), [category, subcategory, diffMin, diffMax])

  const inCollection = useCallback((card: DueCard) => {
    if (!selectedCollection) return true
    return (cardCollections[selectedCollection] || []).includes(card.card_id)
  }, [selectedCollection, cardCollections])

  const loadDue = useCallback(() => {
    api.due({ ...filing(), limit: selectedCollection ? 500 : 100 })
      .then((all) => setCards(all.filter(inCollection)))
      .catch((e: Error) => setError(e.message))
  }, [filing, selectedCollection, inCollection])

  const loadLibrary = useCallback(() => {
    api.cards({ ...filing(), limit: 500 })
      .then((all) => setLibrary(all.filter(inCollection)))
      .catch((e: Error) => setError(e.message))
  }, [filing, inCollection])

  useEffect(loadDue, [loadDue])
  useEffect(() => {
    if (browsing) loadLibrary()
  }, [browsing, loadLibrary])
  useEffect(() => {
    api.stats().then(setStats).catch(() => setStats(null))
    api.followed().then(setFollowed).catch(() => setFollowed([]))
  }, [cards])

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

  const forget = (ids: string[]) => {
    const drop = new Set(ids)
    setCards(list => list?.filter(c => !drop.has(c.card_id)) ?? list)
    setLibrary(list => list?.filter(c => !drop.has(c.card_id)) ?? list)
    setCardCollections(m => {
      const u: Record<string, string[]> = {}
      for (const [name, arr] of Object.entries(m)) u[name] = arr.filter(id => !drop.has(id))
      saveCardCollections(u)
      return u
    })
  }

  const subs = category ? subcategoriesOf(category) : []

  return (
    <div className="practice-page">
      <h1 className="practice-title">Review</h1>
      <div className="practice-layout">
        <aside className="practice-sidebar">
          <div className="sidebar-card">
            <h3 className="sidebar-title">Collections</h3>
            <button
              className={`coll-filter-btn${selectedCollection === null ? ' active' : ''}`}
              onClick={() => setSelectedCollection(null)}
            >
              All cards
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
                aria-label="New collection"
              />
              <button className="coll-add-btn" onClick={createCollection} disabled={!newCollName.trim()}>+</button>
            </div>
          </div>

          <div className="sidebar-card">
            <h3 className="sidebar-title">Filters</h3>
            <label className="filter-label" htmlFor="review-category">Category</label>
            <select
              id="review-category"
              className="filter-select"
              value={category}
              onChange={e => { setCategory(e.target.value); setSubcategory('') }}
            >
              <option value="">All categories</option>
              {categoryNames().map(name => <option key={name} value={name}>{name}</option>)}
            </select>
            <label className="filter-label" htmlFor="review-subcategory">Subcategory</label>
            <select
              id="review-subcategory"
              className="filter-select"
              value={subcategory}
              disabled={!category}
              onChange={e => setSubcategory(e.target.value)}
            >
              <option value="">{category ? 'All subcategories' : 'Pick a category first'}</option>
              {subs.map(name => <option key={name} value={name}>{name}</option>)}
            </select>
            <label className="filter-label">Difficulty</label>
            <div className="filter-diff-row">
              <select
                className="filter-select filter-select-half"
                aria-label="Minimum difficulty"
                value={diffMin ?? ''}
                onChange={e => setDiffMin(e.target.value ? Number(e.target.value) : undefined)}
              >
                <option value="">Min</option>
                {Array.from({ length: 11 }, (_, i) => (
                  <option key={i} value={i}>{DIFFICULTY_LABELS[i]}</option>
                ))}
              </select>
              <span className="filter-dash">–</span>
              <select
                className="filter-select filter-select-half"
                aria-label="Maximum difficulty"
                value={diffMax ?? ''}
                onChange={e => setDiffMax(e.target.value ? Number(e.target.value) : undefined)}
              >
                <option value="">Max</option>
                {Array.from({ length: 11 }, (_, i) => (
                  <option key={i} value={i}>{DIFFICULTY_LABELS[i]}</option>
                ))}
              </select>
            </div>
            <p className="muted filter-note">
              Difficulty is the topic’s usual question difficulty. Cards made before that was stored only appear under All.
            </p>
          </div>
        </aside>

        <div className="practice-center review-center">
          {error && <p className="error">{error}</p>}
          {browsing ? (
            <CardBrowser
              cards={library}
              onClose={() => setBrowsing(false)}
              onDeleted={forget}
              onEdited={(card) => {
                const swap = (list: DueCard[] | null) =>
                  list?.map(c => c.card_id === card.card_id ? card : c) ?? list
                setLibrary(swap)
                setCards(swap)
              }}
            />
          ) : !cards ? (
            error ? null : <p className="muted">Loading…</p>
          ) : !cards.length ? (
            <div className="review-empty">
              <p>
                {selectedCollection
                  ? `No cards in "${selectedCollection}" are due.`
                  : 'Nothing due. Follow topics to make cards, or come back tomorrow.'}
              </p>
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

        <aside className="practice-sidebar">
          <div className="sidebar-card">
            <h3 className="sidebar-title">Stats</h3>
            <div className="review-stats">
              <div><strong>{stats?.reviews_total ?? '—'}</strong><span className="muted">practiced</span></div>
              <div><strong>{stats?.due ?? '—'}</strong><span className="muted">due now</span></div>
              <div><strong>{stats?.cards ?? '—'}</strong><span className="muted">cards</span></div>
              <div><strong>{stats?.reviews_today ?? '—'}</strong><span className="muted">today</span></div>
            </div>
            <ul className="review-rates">
              {RATINGS.map(r => {
                const count = stats?.ratings?.[r.label.toLowerCase() as keyof NonNullable<Stats['ratings']>] ?? 0
                const total = stats?.reviews_total ?? 0
                return (
                  <li key={r.value}>
                    <span style={{ color: r.color }}>{r.label}</span>
                    <span>{total ? percent(count / total) : '—'}{total ? ` · ${count}` : ''}</span>
                  </li>
                )
              })}
            </ul>
            {followed.length > 0 && (
              <ul className="review-topics">
                {followed.map(t => (
                  <li key={t.topic_id}>
                    <Link to={`/topic/${encodeURIComponent(t.topic_id)}`}>
                      <span>{t.name}</span>
                      <span className="muted">{percent(t.accuracy)} · {t.due} due</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
            <button
              className={`primary review-open-btn${browsing ? ' active' : ''}`}
              onClick={() => setBrowsing(open => !open)}
            >
              Review
            </button>
          </div>
        </aside>
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
                style={{ '--rating-color': r.color } as CSSProperties}
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

type CardGrouping = 'none' | 'category' | 'subcategory'
type CardSort = 'front' | 'category' | 'subcategory' | 'due'

function cardFiling(card: DueCard) {
  return {
    category: card.category || 'Uncategorized',
    subcategory: card.subcategory || card.alt_subcategory || 'Uncategorized',
  }
}

function cardSortKey(card: DueCard, sort: CardSort) {
  const filing = cardFiling(card)
  if (sort === 'front') return card.front.toLocaleLowerCase()
  if (sort === 'due') return card.due || ''
  if (sort === 'category') return `${filing.category}\0${filing.subcategory}\0${card.front}`
  return `${filing.subcategory}\0${filing.category}\0${card.front}`
}

function cardGroups(cards: DueCard[], grouping: CardGrouping, sort: CardSort) {
  const sorted = [...cards].sort((a, b) => cardSortKey(a, sort).localeCompare(cardSortKey(b, sort)))
  if (grouping === 'none') return [{ title: '', cards: sorted }]
  const buckets = new Map<string, DueCard[]>()
  for (const card of sorted) {
    const filing = cardFiling(card)
    const title = grouping === 'category' ? filing.category : `${filing.category} · ${filing.subcategory}`
    const list = buckets.get(title) ?? []
    list.push(card)
    buckets.set(title, list)
  }
  return [...buckets.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([title, list]) => ({ title, cards: list }))
}

function CardBrowser({
  cards, onClose, onDeleted, onEdited,
}: {
  cards: DueCard[] | null
  onClose: () => void
  onDeleted: (ids: string[]) => void
  onEdited: (card: DueCard) => void
}) {
  const [selecting, setSelecting] = useState(false)
  const [picked, setPicked] = useState<string[]>([])
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState({ front: '', back: '' })
  const [busy, setBusy] = useState(false)
  const [grouping, setGrouping] = useState<CardGrouping>('none')
  const [sort, setSort] = useState<CardSort>('front')

  const remove = async (ids: string[]) => {
    setBusy(true)
    try {
      await Promise.all(ids.map(id => api.deleteCard(id)))
      onDeleted(ids)
      setPicked(current => current.filter(id => !ids.includes(id)))
    } finally {
      setBusy(false)
    }
  }

  const save = async (card: DueCard) => {
    const front = draft.front.trim()
    const back = draft.back.trim()
    if (!front || !back) return
    setBusy(true)
    try {
      const updated = await api.updateCard(card.card_id, front, back)
      onEdited(updated)
      setEditing(null)
    } finally {
      setBusy(false)
    }
  }

  const groups = cardGroups(cards ?? [], grouping, sort)
  const visibleIds = groups.flatMap(group => group.cards.map(card => card.card_id))
  const allPicked = visibleIds.length > 0 && visibleIds.every(id => picked.includes(id))
  const toggleIds = (ids: string[]) => {
    const every = ids.length > 0 && ids.every(id => picked.includes(id))
    setPicked(current => every
      ? current.filter(id => !ids.includes(id))
      : [...new Set([...current, ...ids])])
  }

  return (
    <div className="card-browser">
      <div className="card-browser-bar">
        <h2 className="sidebar-title" style={{ margin: 0 }}>Your cards</h2>
        <div className="card-browser-actions">
          <button type="button" onClick={() => { setSelecting(s => !s); setPicked([]) }}>
            {selecting ? 'Cancel' : 'Select'}
          </button>
          {selecting && (
            <button type="button" aria-label="Select all cards" onClick={() => toggleIds(visibleIds)}>
              {allPicked ? 'Clear all' : 'Select all'}
            </button>
          )}
          {selecting && (
            <button
              type="button"
              className="card-icon-btn danger"
              disabled={!picked.length || busy}
              onClick={() => void remove(picked)}
            >
              Delete selected{picked.length ? ` (${picked.length})` : ''}
            </button>
          )}
          <button type="button" onClick={onClose}>Study</button>
        </div>
      </div>
      <div className="card-browser-arrange">
        <label>
          Group
          <select aria-label="Group cards" value={grouping} onChange={e => setGrouping(e.target.value as CardGrouping)}>
            <option value="none">None</option>
            <option value="category">Category</option>
            <option value="subcategory">Subcategory</option>
          </select>
        </label>
        <label>
          Sort
          <select aria-label="Sort cards" value={sort} onChange={e => setSort(e.target.value as CardSort)}>
            <option value="front">Front A–Z</option>
            <option value="category">Category</option>
            <option value="subcategory">Subcategory</option>
            <option value="due">Due date</option>
          </select>
        </label>
      </div>
      {!cards ? (
        <p className="muted">Loading cards…</p>
      ) : !cards.length ? (
        <p className="muted">No cards match these filters.</p>
      ) : (
        groups.map(group => {
          const ids = group.cards.map(card => card.card_id)
          const groupPicked = ids.every(id => picked.includes(id))
          return (
            <section key={group.title || 'all'} className="card-group">
              {group.title && (
                <div className="card-group-head">
                  <h3>{group.title}</h3>
                  {selecting && (
                    <button
                      type="button"
                      aria-label={groupPicked ? `Clear ${group.title}` : `Select group ${group.title}`}
                      onClick={() => toggleIds(ids)}
                    >
                      {groupPicked ? 'Clear' : 'Select group'}
                    </button>
                  )}
                </div>
              )}
              <div className="card-grid">
                {group.cards.map(card => {
                  const filing = cardFiling(card)
                  return (
                    <article key={card.card_id} className={`card-tile${selecting ? ' selecting' : ''}`}>
                      {selecting && (
                        <input
                          type="checkbox"
                          className="card-check"
                          aria-label={`Select ${card.front}`}
                          checked={picked.includes(card.card_id)}
                          onChange={() => toggleIds([card.card_id])}
                        />
                      )}
                      {editing === card.card_id ? (
                        <form className="card-edit" onSubmit={e => { e.preventDefault(); void save(card) }}>
                          <textarea aria-label="Card front" value={draft.front} onChange={e => setDraft(d => ({ ...d, front: e.target.value }))} />
                          <textarea aria-label="Card back" value={draft.back} onChange={e => setDraft(d => ({ ...d, back: e.target.value }))} />
                          <div className="card-browser-actions">
                            <button className="primary" type="submit" disabled={busy}>Save</button>
                            <button type="button" onClick={() => setEditing(null)}>Cancel</button>
                          </div>
                        </form>
                      ) : (
                        <div className="card-row-body">
                          <p className="card-row-front">{card.front}</p>
                          <p className="card-row-back muted small">{card.back}</p>
                          <p className="card-tile-filing muted small">{filing.category} · {filing.subcategory}</p>
                        </div>
                      )}
                      {editing !== card.card_id && (
                        <div className="card-row-actions">
                          <button
                            type="button"
                            className="card-icon-btn"
                            aria-label={`Edit ${card.front}`}
                            onClick={() => { setEditing(card.card_id); setDraft({ front: card.front, back: card.back }) }}
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            className="card-icon-btn danger"
                            aria-label={`Delete ${card.front}`}
                            disabled={busy}
                            onClick={() => void remove([card.card_id])}
                          >
                            Delete
                          </button>
                        </div>
                      )}
                    </article>
                  )
                })}
              </div>
            </section>
          )
        })
      )}
    </div>
  )
}
