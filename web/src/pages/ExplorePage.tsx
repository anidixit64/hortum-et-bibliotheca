import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { ExploreResult } from '../api/types'
import { Roulette } from '../components/Roulette'
import { findCategory } from '../lib/categories'
import { useAiMode, useSetAiMode } from '../lib/aiMode'

const DIFFICULTY_LABELS: Record<number, string> = {
  0: 'MS', 1: '1', 2: '2', 3: '3', 4: '4',
  5: '5', 6: '6', 7: '7', 8: '8', 9: '9', 10: 'Open',
}

type ClueSort = 'frequency' | 'rarity'

interface BriefClue { label: string; count: number }

export function ExplorePage() {
  const { slug } = useParams<{ slug: string }>()
  const card = slug ? findCategory(slug) : undefined
  const [results, setResults] = useState<ExploreResult[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [diffMin, setDiffMin] = useState<number | undefined>(undefined)
  const [diffMax, setDiffMax] = useState<number | undefined>(undefined)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [clueCache, setClueCache] = useState<Record<string, BriefClue[]>>({})
  const [clueSort, setClueSort] = useState<ClueSort>('frequency')
  const ai = useAiMode()
  const setAi = useSetAiMode()
  const [roulette, setRoulette] = useState(false)

  useEffect(() => {
    if (!card) return
    setResults(null)
    setError(null)
    setExpanded(null)
    api
      .exploreTop({
        category: card.category,
        subcategory: card.subcategory,
        altSubcategory: card.altSubcategory,
        difficultyMin: diffMin,
        difficultyMax: diffMax,
      })
      .then((data) => {
        setResults(data)
      })
      .catch((e: Error) => setError(e.message))
  }, [card, diffMin, diffMax])

  const toggleExpand = (topicId: string) => {
    if (expanded === topicId) { setExpanded(null); return }
    setExpanded(topicId)
    if (!clueCache[topicId]) {
      api.cluesBrief(topicId).then((clues) => {
        setClueCache((prev) => ({ ...prev, [topicId]: clues }))
      }).catch(() => {})
    }
  }

  const sortedClues = (clues: BriefClue[]) => {
    if (clueSort === 'rarity') return [...clues].sort((a, b) => a.count - b.count)
    return [...clues].sort((a, b) => b.count - a.count)
  }

  if (!card) {
    return (
      <div className="explore-page">
        <p className="error">Category not found.</p>
        <Link to="/search">Back to search</Link>
      </div>
    )
  }

  const setDifficulty = (min?: number, max?: number) => {
    setDiffMin(min)
    setDiffMax(max)
  }

  return (
    <div className="explore-page">
      <div className="explore-header">
        <Link to="/search" className="explore-back">&larr; Browse</Link>
        <h1 className="explore-title">{card.label}</h1>
        <p className="muted explore-subtitle">Top topics by question frequency</p>
      </div>

      <div className="explore-controls">
        <div className="explore-diff-bar">
          <button
            className={`explore-diff-btn${diffMin === undefined && diffMax === undefined ? ' active' : ''}`}
            onClick={() => setDifficulty()}
          >
            All
          </button>
          {Object.entries(DIFFICULTY_LABELS).map(([val, label]) => {
            const n = Number(val)
            return (
              <button
                key={val}
                className={`explore-diff-btn${diffMin === n && diffMax === n ? ' active' : ''}`}
                onClick={() => setDifficulty(n, n)}
              >
                {label}
              </button>
            )
          })}
        </div>
        <button type="button" className="explore-random" onClick={() => setRoulette(true)}>
          Randomizer
        </button>
        <div className="explore-ai-toggle">
          <span className={ai ? 'explore-mode-on' : undefined}>AI</span>
          <button
            type="button"
            className={`nav-switch${ai ? ' on' : ''}`}
            role="switch"
            aria-checked={ai}
            aria-label="AI writing"
            onClick={() => setAi(!ai)}
          >
            <span />
          </button>
          <span className={!ai ? 'explore-mode-on' : undefined}>Non-AI</span>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {!results && !error && <p className="muted">Loading...</p>}
      {results && results.length === 0 && (
        <p className="muted explore-empty">No topics found for this difficulty.</p>
      )}

      {roulette && (
        <>
          <div className="palette-backdrop roulette-backdrop" />
          <div className="roulette-layer" role="dialog" aria-modal="true" aria-label="Random topic">
            <button type="button" className="roulette-back" onClick={() => setRoulette(false)}>
              ← Explore
            </button>
            <Roulette />
          </div>
        </>
      )}

      {results && results.length > 0 && (
        <ol className="explore-results">
          {results.map((r, i) => {
            const isOpen = expanded === r.topic_id
            const clues = clueCache[r.topic_id]
            return (
              <li key={r.topic_id} className={isOpen ? 'explore-li-open' : undefined}>
                <div className="explore-row-wrap">
                  <Link to={`/topic/${encodeURIComponent(r.topic_id)}`} className="explore-row">
                    <span className="explore-rank">{i + 1}</span>
                    <div className="explore-info">
                      <strong>{r.name}</strong>
                      <span className="muted small">{r.count} questions</span>
                    </div>
                  </Link>
                  <button
                    className={`explore-expand-btn${isOpen ? ' open' : ''}`}
                    onClick={() => toggleExpand(r.topic_id)}
                    aria-label={isOpen ? 'Hide clues' : 'Show clues'}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="6 9 12 15 18 9" />
                    </svg>
                  </button>
                </div>
                {isOpen && (
                  <div className="explore-clues">
                    {!clues ? (
                      <p className="muted small">Loading clues...</p>
                    ) : clues.length === 0 ? (
                      <p className="muted small">No clues indexed yet.</p>
                    ) : (
                      <>
                        <div className="explore-clue-header">
                          <span className="muted small">Top clues</span>
                          <button
                            className="explore-clue-sort"
                            onClick={() => setClueSort(clueSort === 'frequency' ? 'rarity' : 'frequency')}
                          >
                            {clueSort === 'frequency' ? 'Most asked' : 'Rarest first'}
                          </button>
                        </div>
                        <ul className="explore-clue-list">
                          {sortedClues(clues).map((c) => (
                            <li key={c.label} className="explore-clue-item">
                              <span className="explore-clue-label">{c.label}</span>
                              <span className="explore-clue-count muted small">{c.count}q</span>
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
