import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { ExploreResult } from '../api/types'
import { findCategory } from '../lib/categories'

const DIFFICULTY_LABELS: Record<number, string> = {
  0: 'MS', 1: '1', 2: '2', 3: '3', 4: '4',
  5: '5', 6: '6', 7: '7', 8: '8', 9: '9', 10: 'Open',
}

export function ExplorePage() {
  const { slug } = useParams<{ slug: string }>()
  const card = slug ? findCategory(slug) : undefined
  const [results, setResults] = useState<ExploreResult[] | null>(null)
  const [thumbs, setThumbs] = useState<Record<string, string | null>>({})
  const [error, setError] = useState<string | null>(null)
  const [diffMin, setDiffMin] = useState<number | undefined>(undefined)
  const [diffMax, setDiffMax] = useState<number | undefined>(undefined)
  const thumbReq = useRef(0)

  useEffect(() => {
    if (!card) return
    setResults(null)
    setError(null)
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
        const ids = data.map((r) => r.topic_id)
        if (ids.length) {
          const req = ++thumbReq.current
          api.thumbnails(ids).then((t) => {
            if (req === thumbReq.current) setThumbs((prev) => ({ ...prev, ...t }))
          }).catch(() => {})
        }
      })
      .catch((e: Error) => setError(e.message))
  }, [card, diffMin, diffMax])

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

      {error && <p className="error">{error}</p>}
      {!results && !error && <p className="muted">Loading...</p>}
      {results && results.length === 0 && (
        <p className="muted explore-empty">No topics found for this difficulty.</p>
      )}

      {results && results.length > 0 && (
        <ol className="explore-results">
          {results.map((r, i) => (
            <li key={r.topic_id}>
              <Link to={`/topic/${encodeURIComponent(r.topic_id)}`} className="explore-row">
                <span className="explore-rank">{i + 1}</span>
                <div className="explore-thumb">
                  {thumbs[r.topic_id] ? (
                    <img src={thumbs[r.topic_id]!} alt="" loading="lazy" />
                  ) : (
                    <div className="explore-thumb-placeholder" />
                  )}
                </div>
                <div className="explore-info">
                  <strong>{r.name}</strong>
                  <span className="muted small">{r.count} questions</span>
                </div>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
