import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { SearchResult } from '../api/types'

const DEBOUNCE_MS = 200

export function SearchBox({ autoFocus = false }: { autoFocus?: boolean }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const q = query.trim()
    if (!q) return
    let cancelled = false
    const timer = setTimeout(() => {
      api
        .search(q)
        .then((found) => !cancelled && (setResults(found), setError(null)))
        .catch((e: Error) => !cancelled && setError(e.message))
    }, DEBOUNCE_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [query])

  return (
    <div>
      <input
        type="search"
        placeholder="Search a topic: soccer, Invisible Man, mitosis…"
        aria-label="Search topics"
        value={query}
        autoFocus={autoFocus}
        onChange={(e) => setQuery(e.target.value)}
      />
      {error && <p className="error">{error}</p>}
      <ul className="results" aria-label="Search results">
        {(query.trim() ? results : []).map((r) => (
          <li key={r.id}>
            <Link to={`/topic/${encodeURIComponent(r.id)}`}>
              <strong>{r.name}</strong>{' '}
              <span className="muted small">
                {r.category ?? 'Uncategorized'} · asked {r.n_tossups}×
                {r.matched_alias.toLowerCase() !== r.name.toLowerCase() && ` · “${r.matched_alias}”`}
              </span>
              {r.description && <div className="muted small">{r.description}</div>}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
